import io
import json
import os
import re
import time
import math
import random
from datetime import datetime, timezone
from typing import Any

import streamlit as st
from PIL import Image, ImageDraw, ImageOps
from google import genai
from google.genai import types

APP_NAME = "SolderSight"
DEFAULT_MODEL = "gemini-3.8-flash"
FALLBACK_MODEL = "gemini-3.5-flash"
MAX_IMAGE_MB = 12
MAX_DIMENSION = 1800

st.set_page_config(
    page_title="SolderSight | PCB Quality Inspection",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
:root { --ink:#142235; --muted:#65758b; --line:#dce4ed; --surface:#f5f8fc; }
.block-container {max-width: 1440px; padding-top: 1.3rem; padding-bottom: 3rem;}
header[data-testid="stHeader"] {background: transparent;}
.brand {display:flex; align-items:center; gap:13px; margin-bottom:5px;}
.brand-mark {width:44px;height:44px;border-radius:13px;display:flex;align-items:center;
justify-content:center;background:#132a43;color:#fff;font-size:23px;}
.brand-name {font-size:29px;font-weight:750;letter-spacing:-.8px;color:#132a43;line-height:1.1;}
.brand-sub {color:#6b7c91;font-size:13px;margin-top:4px;}
.topline {height:1px;background:#dfe7f0;margin:18px 0 22px 0;}
.section-title {font-size:19px;font-weight:700;color:#172a40;margin:8px 0 3px 0;}
.section-help {font-size:13px;color:#6c7c8e;margin-bottom:14px;}
.result-panel {border:1px solid #dce5ee;border-radius:16px;padding:18px 20px;background:#fff;}
.result-label {font-size:12px;text-transform:uppercase;letter-spacing:1.1px;color:#687a8e;font-weight:700;}
.result-value {font-size:25px;font-weight:750;color:#16283d;margin-top:3px;}
.muted {color:#6b7c91;font-size:13px;}
div[data-testid="stMetric"] {border:1px solid #dce5ee;border-radius:13px;padding:12px 15px;background:#fff;}
div.stButton > button {border-radius:10px;font-weight:650;min-height:42px;}
div[data-testid="stFileUploader"] {border:1px dashed #a8b9ca;border-radius:13px;padding:10px;background:#f8fafc;}
footer {visibility:hidden;}
</style>
<div class="brand">
  <div class="brand-mark">⌁</div>
  <div>
    <div class="brand-name">SolderSight</div>
    <div class="brand-sub">PCB solder inspection · Visual quality review</div>
  </div>
</div>
<div class="topline"></div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### Inspection setup")
    model_name = st.text_input(
        "Primary analysis model",
        value=os.environ.get("SOLDERSIGHT_MODEL", DEFAULT_MODEL),
        help=f"Primary model. If it errors, SolderSight tries {FALLBACK_MODEL}. These IDs must be enabled for your API key."
    ).strip() or DEFAULT_MODEL
    st.caption(f"Automatic fallback: `{FALLBACK_MODEL}`")
    enhanced_review = st.toggle(
        "Enhanced review",
        value=True,
        help="Runs a second review of the selected crop. This may cost more and does not guarantee higher accuracy."
    )
    st.markdown("---")
    st.markdown("**Capture guidance**")
    st.markdown(
        "- Photograph a completed joint after the iron is removed.\n"
        "- Keep the camera close and in focus.\n"
        "- Use even lighting; avoid glare.\n"
        "- Include nearby pads so bridges can be assessed."
    )
    st.markdown("---")
    with st.expander("Privacy & system information"):
        st.write(
            "Images selected for analysis are sent to the configured external vision API. "
            "Do not upload confidential board images unless your data policy permits it. "
            "The app does not display provider branding in the inspection interface, but it uses a third-party API behind the scenes."
        )
        st.caption("Visual AI assistance only. It cannot prove electrical continuity, hidden defects, or mechanical strength.")

def get_api_key() -> str | None:
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        key = ""
    return key or os.environ.get("GEMINI_API_KEY")

def new_client():
    key = get_api_key()
    if not key:
        return None
    return genai.Client(api_key=key)

def normalize_image(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
    return img


def click_to_image_pixel(click_value: dict, image: Image.Image):
    """Map rendered image-click coordinates back to the normalized source image."""
    try:
        x, y = float(click_value["x"]), float(click_value["y"])
        dw = float(click_value.get("width") or image.width)
        dh = float(click_value.get("height") or image.height)
        if dw <= 0 or dh <= 0:
            return None
        px = round(x * image.width / dw)
        py = round(y * image.height / dh)
        return (max(0, min(image.width - 1, px)),
                max(0, min(image.height - 1, py)))
    except (KeyError, TypeError, ValueError):
        return None


def crop_around_target(image: Image.Image, point, side_px: int):
    """Return a crop centered on a selected target, clipped to the image bounds."""
    side_px = max(40, int(side_px))
    cx, cy = int(point[0]), int(point[1])
    half = side_px // 2
    left, top = max(0, cx-half), max(0, cy-half)
    right, bottom = min(image.width, cx+half), min(image.height, cy+half)
    if right-left < side_px:
        if left == 0: right = min(image.width, side_px)
        else: left = max(0, image.width-side_px)
    if bottom-top < side_px:
        if top == 0: bottom = min(image.height, side_px)
        else: top = max(0, image.height-side_px)
    return image.crop((left, top, right, bottom))

def as_part(img: Image.Image):
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=94, optimize=True)
    return types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/jpeg")

def parse_json_response(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise ValueError("The analysis service did not return valid JSON. Please retry.")
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Unexpected response format. Please retry.")
    return parsed

def ask_vision_once(client, model: str, prompt: str, img: Image.Image) -> dict[str, Any]:
    response = client.models.generate_content(
        model=model,
        contents=[prompt, as_part(img)],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    return parse_json_response(response.text)


def is_transient_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(term in message for term in (
        "503", "unavailable", "high demand", "429", "resource_exhausted",
        "rate limit", "500", "502", "504", "deadline", "temporarily",
        "internal error", "overloaded", "try again"
    ))


def is_auth_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(term in message for term in (
        "api key not valid", "invalid api key", "unauthenticated", "401"
    ))


def ask_vision(client, model: str, prompt: str, img: Image.Image) -> dict[str, Any]:
    """Try the selected model first, then the configured fallback.

    Retry transient service errors with backoff. Model-not-found/unsupported errors
    move directly to the fallback instead of wasting retries. The same helper is
    used for locate, inspect, and second-review calls.
    """
    models = []
    for candidate in (model, FALLBACK_MODEL):
        candidate = (candidate or "").strip()
        if candidate and candidate not in models:
            models.append(candidate)
    failures = []
    for candidate in models:
        attempts = 3 if candidate == models[0] else 2
        for attempt in range(attempts):
            try:
                result = ask_vision_once(client, candidate, prompt, img)
                if candidate != models[0]:
                    st.info(f"Analysis succeeded using fallback model `{candidate}`.")
                return result
            except Exception as exc:
                failures.append(f"{candidate}: {str(exc)[:240]}")
                message = str(exc).lower()
                model_unavailable = any(term in message for term in (
                    "404", "not found", "unknown model", "model is not found",
                    "not supported for generatecontent", "unsupported model"
                ))
                if is_auth_error(exc):
                    # A second model will not fix a bad key or project permission.
                    raise RuntimeError(
                        "Gemini authentication/permission failed. Check GEMINI_API_KEY and API access. "
                        + str(exc)[:300]
                    ) from exc
                if is_transient_error(exc) and attempt < attempts - 1:
                    wait = min(6.0, 1.0 * (2 ** attempt)) + random.uniform(0, 0.4)
                    time.sleep(wait)
                    continue
                if candidate != models[-1]:
                    reason = "model unavailable" if model_unavailable else "request failed"
                    st.warning(f"`{candidate}` {reason}; trying fallback `{models[models.index(candidate)+1]}`.")
                break
    raise RuntimeError(
        "Both the primary and fallback Gemini model failed. Verify that `gemini-3.8-flash` "
        "and `gemini-3.5-flash` are real, image-capable model IDs enabled for your API project. "
        "Details: " + " | ".join(failures)
    )

LOCATE_PROMPT = """
Task: locate candidate solder joints on a PCB photograph for a human-selected inspection.
Return JSON only:
{"summary":"short summary","joints":[{"joint_id":1,"box_2d":[ymin,xmin,ymax,xmax],"description":"short region description","visibility":"clear|partly_obscured|active_soldering|unclear"}],"limitations":[]}
Coordinates are normalized integers 0–1000 in [ymin,xmin,ymax,xmax] order relative to the full image.
Include plausible solder joints/pads only. Exclude tools, fingers, wire spools, flux containers, and unrelated components.
Be conservative: don't invent regions. Include up to 30 candidates. If there are no confidently identifiable solder joints, return an empty list.
"""

INSPECT_PROMPT = """
You are a careful visual quality-review assistant for PCB solder joints.
Assess only the supplied close-up crop. Do not assume electrical continuity or hidden mechanical integrity.

Return JSON only:
{
 "joint_status":"completed|in_progress|unclear",
 "quality":"good|defective|uncertain",
 "recommendation":"accept|resolder|inspect_further|finish_then_inspect",
 "defects":[{"name":"short defect name","evidence":"specific visible evidence","severity":"minor|moderate|major"}],
 "description":"plain-language description of solder shape, coverage, wetting appearance and relation to neighboring pads",
 "reason":"why the recommendation follows from the visible evidence",
 "confidence":"low|medium|high",
 "image_quality":{"focus":"good|adequate|poor","lighting":"good|adequate|poor","occlusion":"none|partial|major"},
 "limitations":[]
}
Inspection rules:
- Use only visible evidence; don't infer unseen facts.
- A bright or shiny surface alone does not prove quality.
- Call a solder bridge only if solder visibly connects separate pads/pins.
- Excess solder requires visible evidence such as a large uncontrolled mound or bridging; insufficient solder requires visible lack of coverage/contact, not merely a small-looking joint.
- A soldering iron touching the joint, molten solder, or an unfinished process => joint_status=in_progress and recommendation=finish_then_inspect.
- If blur, glare, occlusion, image scale or ambiguous geometry prevents assessment => quality=uncertain, recommendation=inspect_further.
- Use recommendation=resolder only when a visible defect supports rework.
- Use recommendation=accept only when the joint is completed, adequately visible, and no obvious defect is apparent.
- Keep confidence conservative. Do not output numerical accuracy or pretend this is a calibrated probability.
- Mention if the crop contains multiple joints or doesn't isolate a single joint.
"""

VERIFY_PROMPT = """
Independently review this same solder-joint crop for quality-control consistency.
Return JSON only:
{"review_quality":"good|defective|uncertain","review_recommendation":"accept|resolder|inspect_further|finish_then_inspect","agreement":"agree|partly_agree|disagree","missed_concerns":[],"review_note":"short evidence-based note"}
Use conservative visual rules: no claims about hidden defects or electrical continuity; an iron touching/molten solder means finish_then_inspect; uncertain visibility means inspect_further. Do not simply agree with a prior answer; inspect the image independently.
Prior assessment for comparison:
"""

def box_pixels(box, w, h, padding=0.12):
    ymin, xmin, ymax, xmax = [float(v) for v in box]
    x1, y1, x2, y2 = xmin*w/1000, ymin*h/1000, xmax*w/1000, ymax*h/1000
    px, py = (x2-x1)*padding, (y2-y1)*padding
    return max(0,int(x1-px)), max(0,int(y1-py)), min(w,int(x2+px)), min(h,int(y2+py))

def draw_candidate_boxes(img, joints):
    out = img.copy()
    draw = ImageDraw.Draw(out)
    w,h = out.size
    scale = max(2, w//700)
    for j in joints:
        try:
            x1,y1,x2,y2 = box_pixels(j["box_2d"],w,h,0)
            draw.rectangle((x1,y1,x2,y2), outline=(0,190,210), width=scale)
            label = f"Joint {j.get('joint_id','?')}"
            top = max(0,y1-24)
            draw.rectangle((x1,top,min(w,x1+120),y1), fill=(13,49,67))
            draw.text((x1+4,top+4),label,fill=(255,255,255))
        except Exception:
            continue
    return out

def status_banner(recommendation):
    if recommendation == "accept":
        st.success("ACCEPT · No obvious visual defect identified")
    elif recommendation == "resolder":
        st.error("REWORK RECOMMENDED · A visible defect may require resoldering")
    elif recommendation == "finish_then_inspect":
        st.warning("FINISH SOLDERING · Reinspect after the iron is removed and the joint cools")
    else:
        st.warning("INSPECT FURTHER · The image does not support a confident decision")

def run_inspection(client, model, crop, enhanced):
    first = ask_vision(client, model, INSPECT_PROMPT, crop)
    verifier = None
    if enhanced:
        compare = VERIFY_PROMPT + json.dumps(first, ensure_ascii=False)
        try:
            verifier = ask_vision(client, model, compare, crop)
        except Exception as exc:
            verifier = {
                "agreement": "unavailable",
                "review_note": f"Independent review unavailable: {str(exc)[:240]}",
            }
        # Conservative conflict handling: disagreement should not produce an unconditional accept.
        if verifier.get("agreement") == "disagree":
            first["quality"] = "uncertain"
            first["recommendation"] = "inspect_further"
            first.setdefault("limitations", []).append(
                "Two visual reviews disagreed; manual inspection is recommended."
            )
        elif verifier.get("agreement") == "partly_agree":
            if first.get("recommendation") == "accept":
                first["quality"] = "uncertain"
                first["recommendation"] = "inspect_further"
                first.setdefault("limitations", []).append(
                    "The second review raised uncertainty; verify manually."
                )
    return first, verifier

def crop_from_box(image, box):
    return image.crop(box_pixels(box, image.width, image.height, padding=0.18))

# Header summary
st.markdown("### Start an inspection")
st.markdown(
    '<div class="section-help">Upload one clear image. Review the candidate regions, select the actual joint, and inspect the close-up.</div>',
    unsafe_allow_html=True,
)

uploaded = st.file_uploader(
    "Choose a PCB image",
    type=["png","jpg","jpeg","webp"],
    accept_multiple_files=False,
    help=f"PNG, JPG or WEBP · up to {MAX_IMAGE_MB} MB"
)

if uploaded:
    if uploaded.size > MAX_IMAGE_MB*1024*1024:
        st.error(f"Image exceeds {MAX_IMAGE_MB} MB. Please resize it and upload again.")
        st.stop()
    try:
        original = Image.open(uploaded)
        image = normalize_image(original)
    except Exception:
        st.error("This image could not be opened. Try a standard PNG or JPEG.")
        st.stop()

    # Clear stale session state when a different file is uploaded.
    image_key = f"{uploaded.name}:{uploaded.size}:{hash(uploaded.getvalue())}"
    if st.session_state.get("image_key") != image_key:
        for key in ["detection","inspection","verifier","crop","selected_label","report",
                    "cal_ref_a","cal_ref_b","cal_targets","cal_clicked"]:
            st.session_state.pop(key, None)
        st.session_state["image_key"] = image_key
        st.session_state["source_filename"] = uploaded.name

    info1, info2, info3 = st.columns(3)
    info1.metric("Image", uploaded.name[:26] + ("…" if len(uploaded.name)>26 else ""))
    info2.metric("Working resolution", f"{image.width} × {image.height}")
    info3.metric("File size", f"{uploaded.size/1024:.0f} KB")

    # ---------------- XY coordinate calibration / target planning ----------------
    st.markdown("---")
    st.markdown('<div class="section-title">Step 1 of 3 · Calibrate and mark solder targets</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-help">Click two measured reference points on the photo, enter their real distance, then click the solder locations you want to inspect.</div>',
        unsafe_allow_html=True,
    )
    st.info(
        "Calibration assumption: the PCB is approximately planar and the photo has little perspective distortion. "
        "This converts image positions to board-relative coordinates; it does not control a soldering robot."
    )

    st.session_state.setdefault("cal_ref_a", None)
    st.session_state.setdefault("cal_ref_b", None)
    st.session_state.setdefault("cal_targets", [])
    st.session_state.setdefault("cal_clicked", None)

    try:
        from streamlit_image_coordinates import streamlit_image_coordinates
        click_picker_available = True
    except Exception:
        click_picker_available = False

    st.markdown("**Step 1 · Mark the reference points**")
    if click_picker_available:
        st.caption("Click the image to select a point. Then save it as Reference A, Reference B, or a target. Click positions are scaled back to the source-image pixels.")
        click_value = streamlit_image_coordinates(image, key=f"xy_picker_{image_key}")
        if click_value and "x" in click_value and "y" in click_value:
            mapped_point = click_to_image_pixel(click_value, image)
            if mapped_point:
                st.session_state["cal_clicked"] = mapped_point
        if st.session_state.get("cal_clicked"):
            cx, cy = st.session_state["cal_clicked"]
            st.info(f"Selected image point: **({cx}, {cy}) px**. Save it as Reference A, Reference B, or a target below.")
    else:
        st.error("Image-click support is unavailable. Install dependencies with `pip install -r requirements.txt` and restart Streamlit. A manual pixel-entry fallback is shown below.")
        p1, p2 = st.columns(2)
        with p1:
            fallback_x = st.number_input("Clicked X pixel", min_value=0, max_value=image.width-1, value=0, key="fallback_click_x")
        with p2:
            fallback_y = st.number_input("Clicked Y pixel", min_value=0, max_value=image.height-1, value=0, key="fallback_click_y")
        st.session_state["cal_clicked"] = (int(fallback_x), int(fallback_y))
        cx, cy = st.session_state["cal_clicked"]

    ref_cols = st.columns(3)
    if ref_cols[0].button("Save as Reference A", use_container_width=True):
        st.session_state["cal_ref_a"] = st.session_state.get("cal_clicked")
    if ref_cols[1].button("Save as Reference B", use_container_width=True):
        st.session_state["cal_ref_b"] = st.session_state.get("cal_clicked")
    target_label = ref_cols[2].text_input("Target label", value=f"Target {len(st.session_state['cal_targets'])+1}", key="target_label_input")
    if ref_cols[2].button("Add clicked target", use_container_width=True):
        point = st.session_state.get("cal_clicked")
        if point:
            st.session_state["cal_targets"].append({"label": target_label.strip() or f"Target {len(st.session_state['cal_targets'])+1}", "px_x": int(point[0]), "px_y": int(point[1])})

    known_distance = st.number_input(
        "Real distance from Reference A to B (cm)", min_value=0.001, value=25.0, step=0.5, format="%.3f",
        help="Example: enter 25 if the two exact points you clicked are 25 cm apart in real life. Positive X follows A to B."
    )
    invert_y = st.checkbox("Invert Y direction (positive Y points up on the image)", value=False, help="Unchecked means positive Y is perpendicular to A→B in the image-down direction.")
    ra, rb = st.session_state.get("cal_ref_a"), st.session_state.get("cal_ref_b")
    status_cols = st.columns(2)
    status_cols[0].metric("Reference A", f"{ra[0]}, {ra[1]} px" if ra else "Not marked")
    status_cols[1].metric("Reference B", f"{rb[0]}, {rb[1]} px" if rb else "Not marked")

    if ra and rb:
        dx_ref, dy_ref = rb[0]-ra[0], rb[1]-ra[1]
        pixel_distance = math.hypot(dx_ref, dy_ref)
        if pixel_distance < 1:
            st.error("Reference A and B must be different points. Mark them again.")
        else:
            scale_cm_per_px = float(known_distance) / pixel_distance
            ux, uy = dx_ref/pixel_distance, dy_ref/pixel_distance
            # Positive local Y is perpendicular clockwise in image coordinates.
            vx, vy = -uy, ux
            if invert_y:
                vx, vy = -vx, -vy
            st.success(f"Calibration ready · {scale_cm_per_px:.6f} cm/pixel · reference span {pixel_distance:.1f} px")
            rows = []
            for i, point in enumerate(st.session_state["cal_targets"], start=1):
                px_dx, px_dy = point["px_x"]-ra[0], point["px_y"]-ra[1]
                x_cm = (px_dx*ux + px_dy*uy) * scale_cm_per_px
                y_cm = (px_dx*vx + px_dy*vy) * scale_cm_per_px
                rows.append({"Target": point["label"], "Pixel X": point["px_x"], "Pixel Y": point["px_y"], "X (cm)": round(x_cm, 4), "Y (cm)": round(y_cm, 4)})
            if rows:
                st.markdown("**Calibrated target coordinates**")
                st.dataframe(rows, use_container_width=True, hide_index=True)
                import csv
                csv_buffer = io.StringIO()
                writer = csv.DictWriter(csv_buffer, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
                st.download_button("Download XY targets (CSV)", data=csv_buffer.getvalue(), file_name="soldersight_xy_targets.csv", mime="text/csv")
                clear_col, undo_col = st.columns(2)
                with clear_col:
                    if st.button("Clear all targets", key="clear_xy_targets", use_container_width=True):
                        st.session_state["cal_targets"] = []
                        st.rerun()
                with undo_col:
                    if st.button("Undo last target", key="undo_xy_target", use_container_width=True,
                                 disabled=not bool(st.session_state["cal_targets"])):
                        st.session_state["cal_targets"].pop()
                        st.rerun()
            else:
                st.caption("No targets added yet. Click a target location and choose Add clicked target.")

    # Draw reference/target markers over the image for a quick visual check.
    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    marker_radius = max(5, min(image.width, image.height)//100)
    for point, color, label in [(ra, (0, 120, 255), "A"), (rb, (255, 110, 0), "B")]:
        if point:
            x0, y0 = point
            draw.ellipse((x0-marker_radius, y0-marker_radius, x0+marker_radius, y0+marker_radius), outline=color, width=max(2, marker_radius//2))
            draw.text((x0+marker_radius+2, max(0,y0-marker_radius-12)), label, fill=color)
    for idx, point in enumerate(st.session_state["cal_targets"], start=1):
        x0, y0 = point["px_x"], point["px_y"]
        draw.ellipse((x0-marker_radius, y0-marker_radius, x0+marker_radius, y0+marker_radius), fill=(0, 160, 100), outline=(255,255,255), width=2)
        draw.text((x0+marker_radius+2, max(0,y0-marker_radius-12)), str(idx), fill=(0, 120, 75))
    st.image(overlay, caption="Marked image · blue = Reference A, orange = Reference B, green = solder targets", use_container_width=True)

    if st.session_state.get("cal_targets"):
        st.markdown("**Step 3 · Select a marked target to inspect**")
        target_options = {
            f"{p['label']} · pixel ({p['px_x']}, {p['px_y']})": p
            for p in st.session_state["cal_targets"]
        }
        chosen_label = st.selectbox("Which marked solder target should SolderSight inspect?",
                                    list(target_options.keys()), key="xy_inspection_target")
        chosen_target = target_options[chosen_label]
        max_crop = max(80, min(900, max(image.width, image.height)))
        crop_side = st.slider("Inspection crop size (pixels)", min_value=80, max_value=max_crop,
                              value=min(360, max_crop), step=20,
                              help="The crop is centered on your marked point. Include the joint and neighboring pads.")
        target_crop = crop_around_target(image, (chosen_target["px_x"], chosen_target["px_y"]), crop_side)
        prev_col, action_col = st.columns([1, 1], gap="large")
        with prev_col:
            st.image(target_crop, caption=f"Inspection preview: {chosen_target['label']}", use_container_width=True)
        with action_col:
            st.write(f"**Selected target:** {chosen_target['label']}")
            if ra and rb and pixel_distance >= 1:
                target_row = next((r for r in rows if r["Target"] == chosen_target["label"]), None)
                if target_row:
                    st.write(f"**X:** {target_row['X (cm)']:.4f} cm")
                    st.write(f"**Y:** {target_row['Y (cm)']:.4f} cm")
            st.caption("Check the crop before starting the visual review.")
            if st.button("Inspect this marked target", type="primary", use_container_width=True,
                         key="inspect_marked_xy_target"):
                target_client = new_client()
                if target_client is None:
                    st.error("Add GEMINI_API_KEY to Streamlit Secrets or the server environment before inspecting.")
                else:
                    with st.spinner("Inspecting the marked solder target…"):
                        try:
                            report, verifier = run_inspection(target_client, model_name, target_crop, enhanced_review)
                            st.session_state["inspection"] = report
                            st.session_state["verifier"] = verifier
                            st.session_state["report"] = {
                                "application": APP_NAME,
                                "image_filename": uploaded.name,
                                "inspected_at_utc": datetime.now(timezone.utc).isoformat(),
                                "joint_id": chosen_target["label"],
                                "target_pixel": {"x": chosen_target["px_x"], "y": chosen_target["px_y"]},
                                "assessment": report,
                                "second_review": verifier,
                            }
                            st.session_state["inspection_source"] = "marked target"
                            st.success(f"Inspection complete for {chosen_target['label']}. See the report below.")
                        except Exception as exc:
                            st.error(f"Inspection failed: {str(exc)[:600]}")

    st.caption("Calibration assumes a flat PCB, consistent scale, and minimal perspective distortion. For machine use, camera-to-robot calibration, homing, tool-tip offsets, axis/sign validation, and physical safety interlocks are also required. This app does not command hardware.")
    # -----------------------------------------------------------------------------

    with st.expander("Image quality checklist", expanded=False):
        st.write("Before analysis, check that:")
        st.write("- The joint is in focus and large enough to inspect.")
        st.write("- Reflections do not hide the solder-to-pad boundary.")
        st.write("- The soldering iron is no longer touching the joint for final acceptance.")
        st.write("- Adjacent pads are visible when checking for bridges.")

    client = new_client()
    if client is None:
        st.error("Inspection is not configured yet. Add GEMINI_API_KEY to Streamlit Secrets or the server environment.")
        st.code('GEMINI_API_KEY = "your_api_key"', language="toml")
        st.stop()

    col_img, col_actions = st.columns([1.08,0.92], gap="large")
    with col_img:
        st.markdown('<div class="section-title">Image preview</div>', unsafe_allow_html=True)
        st.image(image, use_container_width=True)
    with col_actions:
        st.markdown('<div class="section-title">Inspection workflow</div>', unsafe_allow_html=True)
        st.markdown("**01 · Locate joints**")
        st.caption("Find likely solder regions. You will choose which one to inspect.")
        locate = st.button("Find candidate joints", type="primary", use_container_width=True)
        if locate:
            with st.spinner("Reviewing the image for candidate solder joints…"):
                try:
                    det = ask_vision(client, model_name, LOCATE_PROMPT, image)
                    joints = det.get("joints", [])
                    # Normalize/validate IDs and coordinates.
                    valid = []
                    for idx,j in enumerate(joints[:30], start=1):
                        b = j.get("box_2d")
                        if isinstance(b,list) and len(b)==4:
                            try:
                                b = [max(0,min(1000,int(float(v)))) for v in b]
                                if b[2] > b[0] and b[3] > b[1]:
                                    j["box_2d"] = b
                                    j["joint_id"] = j.get("joint_id",idx)
                                    valid.append(j)
                            except (ValueError,TypeError):
                                pass
                    det["joints"] = valid
                    st.session_state["detection"] = det
                    st.session_state.pop("inspection",None)
                    st.session_state.pop("verifier",None)
                except Exception as exc:
                    st.error(f"Could not locate joints: {str(exc)[:500]}")
        st.markdown("**02 · Select a joint**")
        st.caption("Candidate boxes are suggestions. Confirm the box covers the actual solder.")
        st.markdown("**03 · Inspect and review**")
        st.caption("The selected close-up is checked for visible quality issues and a recommended next step.")

    detection = st.session_state.get("detection")
    if detection:
        joints = detection.get("joints", [])
        st.markdown("---")
        st.markdown('<div class="section-title">Candidate regions</div>', unsafe_allow_html=True)
        if joints:
            st.image(draw_candidate_boxes(image,joints), use_container_width=True)
            st.caption(detection.get("summary","Review the boxes before choosing a joint."))
            option_map = {}
            for idx,j in enumerate(joints):
                label = f"Joint {j['joint_id']} · {j.get('description','Candidate region')[:90]}"
                option_map[label] = j
            selected_label = st.selectbox("Which box contains the solder you want to inspect?", list(option_map.keys()))
            selected_joint = option_map[selected_label]
            crop = crop_from_box(image, selected_joint["box_2d"])
            st.session_state["crop"] = crop
            st.session_state["selected_label"] = selected_label
            crop_col, details_col = st.columns([1,1], gap="large")
            with crop_col:
                st.markdown('<div class="section-title">Selected joint</div>', unsafe_allow_html=True)
                st.image(crop, caption="This close-up will be sent for assessment.", use_container_width=True)
            with details_col:
                st.markdown('<div class="section-title">Region details</div>', unsafe_allow_html=True)
                st.write(f"**Joint:** {selected_joint['joint_id']}")
                st.write(f"**Visibility estimate:** {selected_joint.get('visibility','not specified').replace('_',' ').title()}")
                st.write(f"**Region:** {selected_joint.get('description','Candidate solder region')}")
                inspect_btn = st.button("Inspect this joint", type="primary", use_container_width=True)
                if inspect_btn:
                    with st.spinner("Assessing visible solder quality…"):
                        try:
                            report, verifier = run_inspection(client, model_name, crop, enhanced_review)
                            st.session_state["inspection"] = report
                            st.session_state["verifier"] = verifier
                            st.session_state["report"] = {
                                "application": APP_NAME,
                                "image_filename": uploaded.name,
                                "inspected_at_utc": datetime.now(timezone.utc).isoformat(),
                                "joint_id": selected_joint["joint_id"],
                                "assessment": report,
                                "second_review": verifier,
                            }
                        except Exception as exc:
                            st.error(f"Inspection failed: {str(exc)[:600]}")
        else:
            st.warning("No candidate joints were returned. You can manually choose a crop below.")

        with st.expander("Manual crop selection", expanded=not bool(joints)):
            st.caption("Use this when the automatic boxes miss the joint. Adjust the rectangle in image-pixel coordinates.")
            a,b,c,d = st.columns(4)
            x = a.number_input("Left (px)", min_value=0, max_value=max(0,image.width-1), value=0, step=max(1,image.width//20))
            y = b.number_input("Top (px)", min_value=0, max_value=max(0,image.height-1), value=0, step=max(1,image.height//20))
            cw = c.number_input("Width (px)", min_value=1, max_value=image.width, value=max(1,image.width//4), step=max(1,image.width//20))
            ch = d.number_input("Height (px)", min_value=1, max_value=image.height, value=max(1,image.height//4), step=max(1,image.height//20))
            mx,my = min(image.width,int(x+cw)), min(image.height,int(y+ch))
            manual_crop = image.crop((int(x),int(y),mx,my))
            st.image(manual_crop, caption="Manual crop preview", width=520)
            if st.button("Inspect manual crop", key="manual_inspect", type="secondary"):
                with st.spinner("Assessing selected crop…"):
                    try:
                        report, verifier = run_inspection(client, model_name, manual_crop, enhanced_review)
                        st.session_state["inspection"] = report
                        st.session_state["verifier"] = verifier
                        st.session_state["report"] = {
                            "application": APP_NAME,
                            "image_filename": uploaded.name,
                            "inspected_at_utc": datetime.now(timezone.utc).isoformat(),
                            "joint_id": "manual crop",
                            "assessment": report,
                            "second_review": verifier,
                        }
                    except Exception as exc:
                        st.error(f"Inspection failed: {str(exc)[:600]}")

    report = st.session_state.get("inspection")
    if report:
        st.markdown("---")
        st.markdown('<div class="section-title">Inspection report</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-help">Review the visual evidence and recommended action before making a quality decision.</div>', unsafe_allow_html=True)
        status_banner(report.get("recommendation","inspect_further"))
        m1,m2,m3 = st.columns(3)
        m1.metric("Visual assessment", report.get("quality","uncertain").replace("_"," ").title())
        m2.metric("Joint status", report.get("joint_status","unclear").replace("_"," ").title())
        m3.metric("Confidence", report.get("confidence","low").title())
        st.markdown("#### Description")
        st.write(report.get("description","No description provided."))
        defects = report.get("defects",[])
        st.markdown("#### Visible findings")
        if defects:
            for defect in defects:
                if isinstance(defect,dict):
                    severity = defect.get("severity","unspecified").title()
                    st.markdown(f"**{defect.get('name','Finding')}** · {severity}")
                    st.write(defect.get("evidence",""))
                else:
                    st.write(f"- {defect}")
        else:
            st.write("No specific visible defect was reported. This is not proof that the joint is defect-free.")
        st.markdown("#### Why this action was recommended")
        st.write(report.get("reason",""))
        iq = report.get("image_quality",{})
        if iq:
            with st.expander("Image quality and limitations"):
                st.write(f"**Focus:** {iq.get('focus','not assessed').title()}")
                st.write(f"**Lighting:** {iq.get('lighting','not assessed').title()}")
                st.write(f"**Occlusion:** {iq.get('occlusion','not assessed').title()}")
                for item in report.get("limitations",[]):
                    st.write(f"- {item}")
        verifier = st.session_state.get("verifier")
        if enhanced_review and verifier:
            with st.expander("Consistency review"):
                st.write("**Agreement:**", verifier.get("agreement","unavailable").replace("_"," ").title())
                st.write(verifier.get("review_note",""))
                concerns = verifier.get("missed_concerns",[])
                if concerns:
                    st.write("**Additional concerns:**")
                    for concern in concerns:
                        st.write(f"- {concern}")
        st.download_button(
            "Download inspection report (JSON)",
            data=json.dumps(st.session_state.get("report",report),indent=2,ensure_ascii=False),
            file_name="soldersight_inspection_report.json",
            mime="application/json",
            type="primary",
        )
        st.caption(
            "Important: this is image-based decision support. Verify critical joints using appropriate inspection methods. "
            "Visual analysis cannot confirm electrical continuity or hidden defects."
        )
else:
    st.markdown("---")
    c1,c2,c3 = st.columns(3)
    with c1:
        st.markdown("#### 1. Upload")
        st.write("Start with a clear photo of a PCB or soldered area.")
    with c2:
        st.markdown("#### 2. Select")
        st.write("Review candidate regions and choose the joint you want assessed.")
    with c3:
        st.markdown("#### 3. Inspect")
        st.write("Get an evidence-based description and a conservative recommended action.")
    st.info("For the most useful assessment, upload a close-up of a completed solder joint with the neighboring pads visible.")
