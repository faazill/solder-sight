"""
Solder Sight
Capture or upload a PCB image -> drag a reference box -> enter its real
width/height -> click joints -> get X/Y in mm from the box's bottom-left corner.

Install:
    pip install streamlit pillow "streamlit-image-coordinates>=0.2.0"

Run:
    streamlit run solder_sight.py

Camera note: browsers only allow camera access on https:// or http://localhost.
"""

import csv
import hashlib
import io

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
from streamlit_image_coordinates import streamlit_image_coordinates


# =========================================================
# CONFIGURATION
# =========================================================

st.set_page_config(page_title="Solder Sight", page_icon="🎯", layout="wide")

PANEL_W = 960
PANEL_H = 540
MIN_BOX_PX = 8

INK = "#16212B"
ACCENT = "#0E7C86"
MARK = (255, 59, 48)

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

    html, body, [class*="css"], .stApp {{
        font-family: 'IBM Plex Sans', system-ui, sans-serif;
        color: {INK};
    }}
    .stApp {{ background: #F4F6F7; }}
    .block-container {{ padding-top: 2rem; max-width: 1200px; }}

    h1, h2, h3 {{ letter-spacing: -0.01em; color: {INK}; }}

    .brand {{ display:flex; align-items:baseline; gap:.75rem; margin-bottom:.25rem; }}
    .brand .name {{ font-size:1.9rem; font-weight:600; }}
    .brand .tag {{ color:#5B6B78; font-size:.95rem; }}

    .stepper {{ display:flex; gap:.5rem; margin:1rem 0 1.5rem; }}
    .step {{
        flex:1; padding:.7rem .9rem; border-radius:6px;
        background:#E6EBEE; color:#5B6B78; font-size:.92rem;
        border-left:4px solid #C5CED4;
    }}
    .step b {{ display:block; font-weight:600; }}
    .step.active {{ background:#fff; color:{INK}; border-left-color:{ACCENT};
                    box-shadow:0 1px 3px rgba(22,33,43,.12); }}
    .step.done {{ background:#DCEFF0; color:#0B5A62; border-left-color:{ACCENT}; }}

    .panel {{
        background:#fff; border:1px solid #D9E0E4; border-radius:8px;
        padding:1.1rem 1.25rem; margin-bottom:1rem;
    }}
    .hint {{ color:#5B6B78; font-size:.92rem; margin:.1rem 0 .8rem; }}

    [data-testid="stMetricValue"] {{ font-family:'IBM Plex Mono', monospace; font-size:1.35rem; }}
    [data-testid="stSidebar"] {{ background:#fff; border-right:1px solid #D9E0E4; }}
    .stButton > button[kind="primary"], .stDownloadButton > button {{
        border-radius:6px; font-weight:500;
    }}
    code, pre {{ font-family:'IBM Plex Mono', monospace !important; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================================================
# SESSION STATE
# =========================================================

DEFAULTS = {
    "image_hash": None,
    "image_bytes": None,
    "box_draft": None,       # (x1, y1, x2, y2) in original pixels, not yet confirmed
    "box": None,             # confirmed reference box, integer original pixels
    "width_mm": 100.0,
    "height_mm": 60.0,
    "calibrated": False,
    "cal_id": 0,             # bumps on each calibration so the click widget resets
    "points": [],            # list of (x, y) in original image pixels
    "last_click_sig": None,
    "last_drag_sig": None,
}
for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)

ss = st.session_state


def reset_calibration():
    ss.box_draft = None
    ss.box = None
    ss.calibrated = False
    ss.points = []
    ss.last_click_sig = None
    ss.last_drag_sig = None


# =========================================================
# HELPERS
# =========================================================

def get_font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def fit_image(image, w, h, background=(28, 36, 43)):
    """Fit image into a fixed w x h panel, keeping aspect ratio, centered."""
    image = image.convert("RGB")
    sw, sh = image.size
    scale = min(w / sw, h / sh)
    dw, dh = max(1, round(sw * scale)), max(1, round(sh * scale))
    resized = image.resize((dw, dh), Image.Resampling.LANCZOS)
    panel = Image.new("RGB", (w, h), background)
    ox, oy = (w - dw) // 2, (h - dh) // 2
    panel.paste(resized, (ox, oy))
    return panel, scale, ox, oy, dw, dh


def panel_to_image(x, y, scale, ox, oy):
    return (x - ox) / scale, (y - oy) / scale


def image_to_panel(x, y, scale, ox, oy):
    return x * scale + ox, y * scale + oy


def px_to_mm(point, box, width_mm, height_mm):
    """Origin = bottom-left of the reference box. X right, Y up."""
    x1, y1, x2, y2 = box
    x_mm = (point[0] - x1) / (x2 - x1) * width_mm
    y_mm = (y2 - point[1]) / (y2 - y1) * height_mm
    return x_mm, y_mm


def stepper(stage):
    names = [
        ("Capture image", "Camera or file"),
        ("Reference box", "Drag and set size"),
        ("Pick joints", "Click to measure"),
    ]
    html = '<div class="stepper">'
    for i, (title, sub) in enumerate(names, start=1):
        cls = "done" if i < stage else "active" if i == stage else ""
        html += f'<div class="step {cls}"><b>{i}. {title}</b>{sub}</div>'
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


# =========================================================
# HEADER
# =========================================================

st.markdown(
    '<div class="brand"><span class="name">Solder Sight</span>'
    '<span class="tag">Measure solder-joint positions from a reference box</span></div>',
    unsafe_allow_html=True,
)
st.caption(
    "Creates a coordinate table and G-code preview only. "
    "It does not control any soldering hardware."
)

stage = 1
if ss.image_bytes is not None:
    stage = 3 if ss.calibrated else 2
stepper(stage)


# =========================================================
# STEP 1: CAPTURE OR UPLOAD
# =========================================================

with st.container():
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("1. Capture image")

    source = st.radio(
        "Image source",
        ["Camera", "Upload file"],
        horizontal=True,
        label_visibility="collapsed",
    )

    new_bytes = None
    if source == "Camera":
        st.markdown(
            '<div class="hint">Allow camera access when your browser asks, '
            "then take a photo. Keep the camera steady and facing the board "
            "straight on.</div>",
            unsafe_allow_html=True,
        )
        shot = st.camera_input("Camera", label_visibility="collapsed")
        if shot is not None:
            new_bytes = shot.getvalue()
    else:
        up = st.file_uploader(
            "Image file",
            type=["png", "jpg", "jpeg", "webp", "bmp"],
            label_visibility="collapsed",
        )
        if up is not None:
            new_bytes = up.getvalue()

    st.markdown("</div>", unsafe_allow_html=True)

if new_bytes is not None:
    h = hashlib.sha256(new_bytes).hexdigest()
    if h != ss.image_hash:
        ss.image_hash = h
        ss.image_bytes = new_bytes
        reset_calibration()
        st.rerun()

if ss.image_bytes is None:
    st.info("Take a photo or upload an image to start.")
    st.stop()

try:
    image = Image.open(io.BytesIO(ss.image_bytes)).convert("RGB")
except Exception:
    st.error("This file could not be opened as an image. Try another one.")
    st.stop()

img_w, img_h = image.size
image_hash = ss.image_hash


# =========================================================
# SIDEBAR
# =========================================================

with st.sidebar:
    st.header("Session")
    st.metric("Image", f"{img_w} × {img_h} px")
    if ss.calibrated:
        st.metric("Reference box", f"{ss.width_mm:g} × {ss.height_mm:g} mm")
    st.metric("Points", len(ss.points))

    st.divider()
    st.markdown(
        "**Coordinate system**  \n"
        "Origin (0, 0) is the **bottom-left** corner of the reference box. "
        "X increases to the right, Y increases upward."
    )

    st.divider()
    if ss.calibrated:
        if st.button("Undo last point", disabled=not ss.points):
            ss.points.pop()
            st.rerun()
        if st.button("Clear all points", disabled=not ss.points):
            ss.points = []
            ss.last_click_sig = None
            st.rerun()
        if st.button("Redraw reference box"):
            reset_calibration()
            st.rerun()


# =========================================================
# STEP 2: DRAW REFERENCE BOX
# =========================================================

if not ss.calibrated:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("2. Draw the reference box")
    st.markdown(
        '<div class="hint">Drag from one corner to the opposite corner around '
        "an object of known size (the PCB, or a ruler-marked rectangle). "
        "Then enter its real width and height.</div>",
        unsafe_allow_html=True,
    )

    panel, scale, ox, oy, dw, dh = fit_image(image, PANEL_W, PANEL_H)

    if ss.box_draft is not None:
        d = ImageDraw.Draw(panel, "RGBA")
        bx1, by1, bx2, by2 = ss.box_draft
        p1 = image_to_panel(bx1, by1, scale, ox, oy)
        p2 = image_to_panel(bx2, by2, scale, ox, oy)
        d.rectangle((*p1, *p2), fill=(14, 124, 134, 50), outline=(14, 200, 214, 255), width=3)
        # origin marker at bottom-left of the box
        cx, cy = p1[0], p2[1]
        d.ellipse((cx - 7, cy - 7, cx + 7, cy + 7), fill=(255, 59, 48, 255), outline="white", width=2)
        d.text((cx + 12, cy - 22), "Origin (0, 0)", fill="white", font=get_font(15),
               stroke_width=2, stroke_fill=(0, 0, 0))

    try:
        drag = streamlit_image_coordinates(
            panel,
            key=f"box_drag_{image_hash}",
            click_and_drag=True,
        )
    except TypeError:
        st.error(
            "Box drawing needs a newer component. Run: "
            'pip install -U "streamlit-image-coordinates>=0.2.0"'
        )
        st.stop()

    if drag and all(k in drag for k in ("x1", "y1", "x2", "y2")):
        sig = (drag["x1"], drag["y1"], drag["x2"], drag["y2"])
        if sig != ss.last_drag_sig:
            ss.last_drag_sig = sig
            ax, ay = panel_to_image(min(sig[0], sig[2]), min(sig[1], sig[3]), scale, ox, oy)
            bx, by = panel_to_image(max(sig[0], sig[2]), max(sig[1], sig[3]), scale, ox, oy)
            ax, bx = (max(0.0, min(img_w - 1.0, v)) for v in (ax, bx))
            ay, by = (max(0.0, min(img_h - 1.0, v)) for v in (ay, by))
            if bx - ax >= MIN_BOX_PX and by - ay >= MIN_BOX_PX:
                ss.box_draft = (ax, ay, bx, by)
                st.rerun()
            else:
                st.warning("That box is too small. Drag a larger rectangle.")

    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("Reference size")
    c1, c2, c3 = st.columns([1, 1, 1.2])
    width_mm = c1.number_input("Box width (mm)", 0.1, 10000.0, float(ss.width_mm), 1.0)
    height_mm = c2.number_input("Box height (mm)", 0.1, 10000.0, float(ss.height_mm), 1.0)

    c3.markdown("&nbsp;", unsafe_allow_html=True)
    if c3.button("Confirm reference box", type="primary", disabled=ss.box_draft is None):
        ss.box = tuple(int(round(v)) for v in ss.box_draft)
        ss.width_mm = float(width_mm)
        ss.height_mm = float(height_mm)
        ss.calibrated = True
        ss.cal_id += 1
        ss.points = []
        ss.last_click_sig = None
        st.rerun()

    if ss.box_draft is None:
        st.caption("Draw a box on the image to enable this button.")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()


# =========================================================
# STEP 3: PICK POINTS INSIDE THE BOX
# =========================================================

x1, y1, x2, y2 = ss.box
crop = image.crop((x1, y1, x2, y2))

if crop.width < 2 or crop.height < 2:
    st.error("The reference box is too small. Redraw it from the sidebar.")
    st.stop()

st.markdown('<div class="panel">', unsafe_allow_html=True)
st.subheader("3. Pick solder joints")
st.markdown(
    '<div class="hint">Click a joint to add it. Each click is measured in mm '
    "from the bottom-left corner of the reference box (red origin marker).</div>",
    unsafe_allow_html=True,
)

crop_panel, c_scale, c_ox, c_oy, c_dw, c_dh = fit_image(crop, PANEL_W, PANEL_H)
d = ImageDraw.Draw(crop_panel, "RGBA")

# Axes at the origin (bottom-left of the displayed crop)
org_x, org_y = c_ox, c_oy + c_dh
arm = 70
d.line((org_x, org_y, org_x + arm, org_y), fill=(255, 59, 48, 255), width=3)
d.line((org_x, org_y, org_x, org_y - arm), fill=(52, 199, 89, 255), width=3)
d.ellipse((org_x - 6, org_y - 6, org_x + 6, org_y + 6), fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
f_small = get_font(14)
d.text((org_x + arm + 6, org_y - 18), "X", fill="white", font=f_small, stroke_width=2, stroke_fill=(0, 0, 0))
d.text((org_x + 8, org_y - arm - 20), "Y", fill="white", font=f_small, stroke_width=2, stroke_fill=(0, 0, 0))

# Point markers
f_pt = get_font(16)
for i, (px, py) in enumerate(ss.points, start=1):
    cx, cy = image_to_panel(px - x1, py - y1, c_scale, c_ox, c_oy)
    d.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), outline=MARK + (255,), width=3)
    d.line((cx - 4, cy, cx + 4, cy), fill=MARK + (255,), width=2)
    d.line((cx, cy - 4, cx, cy + 4), fill=MARK + (255,), width=2)
    d.text((cx + 13, cy - 20), str(i), fill="white", font=f_pt, stroke_width=2, stroke_fill=(0, 0, 0))

click = streamlit_image_coordinates(crop_panel, key=f"pick_{image_hash}_{ss.cal_id}")

if click:
    sig = (click.get("x"), click.get("y"), click.get("unix_time"))
    if sig != ss.last_click_sig:
        ss.last_click_sig = sig
        cx_img, cy_img = panel_to_image(click["x"], click["y"], c_scale, c_ox, c_oy)
        if 0 <= cx_img < crop.width and 0 <= cy_img < crop.height:
            ss.points.append((x1 + cx_img, y1 + cy_img))
            st.rerun()
        else:
            st.warning("That click was outside the reference box.")

st.markdown("</div>", unsafe_allow_html=True)


# =========================================================
# RESULTS
# =========================================================

rows = []
for i, p in enumerate(ss.points, start=1):
    xm, ym = px_to_mm(p, ss.box, ss.width_mm, ss.height_mm)
    rows.append(
        {
            "Point": i,
            "X (mm)": round(xm, 3),
            "Y (mm)": round(ym, 3),
            "Image X (px)": round(p[0], 1),
            "Image Y (px)": round(p[1], 1),
        }
    )

st.markdown('<div class="panel">', unsafe_allow_html=True)
st.subheader("Coordinates")
if rows:
    last = rows[-1]
    m1, m2, m3 = st.columns(3)
    m1.metric("Latest point", f"#{last['Point']}")
    m2.metric("X", f"{last['X (mm)']:.3f} mm")
    m3.metric("Y", f"{last['Y (mm)']:.3f} mm")
    st.dataframe(rows, hide_index=True)
else:
    st.info("No points yet. Click a solder joint in the image above.")
st.markdown("</div>", unsafe_allow_html=True)


# =========================================================
# EXPORT
# =========================================================

if rows:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("Export")
    st.caption(
        "G-code contains XY moves only (no Z, no soldering action). "
        "Coordinates are relative to the reference box, not your machine's home."
    )

    lines = [
        "; Solder Sight - XY points (origin = bottom-left of reference box)",
        "; Review and validate before machine execution",
        "G21 ; millimetres",
        "G90 ; absolute positioning",
    ]
    lines += [f"G0 X{r['X (mm)']:.3f} Y{r['Y (mm)']:.3f} ; point {r['Point']}" for r in rows]
    lines.append("M2 ; end program")
    gcode = "\n".join(lines)

    st.code(gcode, language="text")

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

    b1, b2 = st.columns(2)
    b1.download_button("Download G-code", gcode, "solder_sight_points.gcode", "text/plain")
    b2.download_button("Download CSV", buf.getvalue(), "solder_sight_coordinates.csv", "text/csv")
    st.markdown("</div>", unsafe_allow_html=True)

st.caption(
    "Accuracy depends on how precisely the box matches the real object and on "
    "the camera facing the board straight on. Verify axis directions, offsets "
    "and limits before using any coordinates on a machine."
)
