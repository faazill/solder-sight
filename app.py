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
FALLBACK_MODEL = "gemini-2.5-flash-lite"
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
You are analyzing a PCB image to propose candidate solder-work locations for human review.
Return valid JSON only, matching this schema:
{"summary":"short overview","joints":[{"joint_id":1,"box_2d":[ymin,xmin,ymax,xmax],"point_2d":[y,x],"action":"SOLDER|DESOLDER|INSPECT","description":"short location description","reason":"visible evidence for the proposed action","confidence":"low|medium|high","visibility":"clear|partly_obscured|active_soldering|unclear"}],"limitations":[]}
All coordinates are normalized integers from 0 to 1000 relative to the FULL image. box_2d order is [ymin,xmin,ymax,xmax]. point_2d order is [y,x] and should mark the exact recommended tool-contact target (center of the pad/joint), not the center of a broad component. Do not return coordinates in centimeters; the application calculates those from the user's entered physical board dimensions.
Action rules:
- SOLDER: a clearly visible pad/joint appears unpopulated or has visibly insufficient solder and likely needs solder added.
- DESOLDER: visible evidence supports removing solder, such as a solder bridge, obvious excess solder, or a clearly defective joint that needs removal/rework. Do NOT choose DESOLDER merely because a joint already has solder.
- INSPECT: evidence is ambiguous, the target is obscured, or the image cannot justify either action confidently.
Give a short evidence-based reason and conservative confidence. Do not claim certainty from a single photograph. Include up to 30 useful candidates, ordered by priority. Exclude tools, fingers, labels, and unrelated components. If no candidates can be identified, return an empty joints list and explain why in limitations.
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
    """Overlay candidate region boxes and their proposed action/contact point."""
    out = img.copy()
    draw = ImageDraw.Draw(out)
    w, h = out.size
    scale = max(2, w // 700)
    colors = {"SOLDER": (20, 155, 85), "DESOLDER": (220, 70, 55), "INSPECT": (230, 155, 25)}
    for idx, j in enumerate(joints, start=1):
        try:
            x1, y1, x2, y2 = box_pixels(j["box_2d"], w, h, 0)
            action = str(j.get("action", "INSPECT")).upper()
            color = colors.get(action, colors["INSPECT"])
            draw.rectangle((x1, y1, x2, y2), outline=color, width=scale)
            point = j.get("point_2d")
            if isinstance(point, list) and len(point) == 2:
                py, px = float(point[0]), float(point[1])
                cx, cy = int(px * w / 1000), int(py * h / 1000)
            else:
                cx, cy = (x1+x2)//2, (y1+y2)//2
            r = max(5, scale * 3)
            draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=color, outline=(255,255,255), width=max(1, scale//2))
            label = f"{j.get('joint_id', idx)} {action}"
            top = max(0, y1-24)
            label_right = min(w, x1 + max(100, len(label)*8))
            draw.rectangle((x1, top, label_right, y1), fill=color)
            draw.text((x1+4, top+4), label, fill=(255,255,255))
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
    '<div class="section-help">Upload a clear PCB image, draw a work-area crop, enter the measured board dimensions, and ask Gemini to suggest solder-work targets with X/Y coordinates.</div>',
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
                    "cal_ref_a","cal_ref_b","cal_targets","cal_clicked","crop_box_px","manual_workarea_crop"]:
            st.session_state.pop(key, None)
        st.session_state["image_key"] = image_key
        st.session_state["source_filename"] = uploaded.name

    info1, info2, info3 = st.columns(3)
    info1.metric("Image", uploaded.name[:26] + ("…" if len(uploaded.name)>26 else ""))
    info2.metric("Working resolution", f"{image.width} × {image.height}")
    info3.metric("File size", f"{uploaded.size/1024:.0f} KB")

    # ---------------- Interactive work-area crop ----------------
    st.markdown("---")
    st.markdown('<div class="section-title">Draw the work-area / crop box</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-help">Drag a rectangle from one corner to the opposite corner around the PCB area you want to work on. No reference-point step is required. This is only an image selection; it does not move hardware.</div>',
        unsafe_allow_html=True,
    )

    # Optional physical board dimensions let us estimate the drawn box size in cm
    # without requiring the separate reference-point workflow.
    dim_col1, dim_col2 = st.columns(2)
    with dim_col1:
        board_width_cm = st.number_input(
            "Reference PCB width (cm)", min_value=0.0, value=0.0, step=0.5,
            key="crop_board_width_cm",
            help="Measured physical width represented by the full image, used to convert AI target X positions into centimetres."
        )
    with dim_col2:
        board_height_cm = st.number_input(
            "Reference PCB height (cm)", min_value=0.0, value=0.0, step=0.5,
            key="crop_board_height_cm",
            help="Measured physical height represented by the full image, used to convert AI target Y positions into centimetres."
        )

    try:
        from streamlit_drawable_canvas import st_canvas
        canvas_available = True
    except Exception:
        canvas_available = False

    if canvas_available:
        # Keep a manageable display size while preserving the source-image aspect ratio.
        canvas_w = int(min(1000, image.width))
        canvas_h = int(max(1, round(image.height * canvas_w / image.width)))
        if canvas_h > 680:
            canvas_h = 680
            canvas_w = int(max(1, round(image.width * canvas_h / image.height)))
        canvas_bg = image.resize((canvas_w, canvas_h), Image.Resampling.LANCZOS).convert("RGB")
        try:
            crop_canvas = st_canvas(
                fill_color="rgba(30, 144, 255, 0.16)",
                stroke_width=3,
                stroke_color="#1685ff",
                background_image=canvas_bg,
                update_streamlit=True,
                height=int(canvas_h),
                width=int(canvas_w),
                drawing_mode="rect",
                key=f"crop_canvas_{image_key}",
            )
            crop_box = None
            objects = (crop_canvas.json_data or {}).get("objects", []) if crop_canvas else []
            rects = [obj for obj in objects if obj.get("type") == "rect"
                     and float(obj.get("width", 0)) > 1 and float(obj.get("height", 0)) > 1]
            if rects:
                obj = rects[-1]
                left = float(obj.get("left", 0))
                top = float(obj.get("top", 0))
                rw = float(obj.get("width", 0)) * float(obj.get("scaleX", 1))
                rh = float(obj.get("height", 0)) * float(obj.get("scaleY", 1))
                x1 = max(0, min(image.width, round(left * image.width / canvas_w)))
                y1 = max(0, min(image.height, round(top * image.height / canvas_h)))
                x2 = max(0, min(image.width, round((left + rw) * image.width / canvas_w)))
                y2 = max(0, min(image.height, round((top + rh) * image.height / canvas_h)))
                if x2 > x1 and y2 > y1:
                    crop_box = (x1, y1, x2, y2)
                    st.session_state["crop_box_px"] = crop_box
            else:
                crop_box = st.session_state.get("crop_box_px")

            if crop_box:
                x1, y1, x2, y2 = crop_box
                roi = image.crop(crop_box)
                crop_cols = st.columns([1, 1])
                with crop_cols[0]:
                    st.image(roi, caption="Selected crop preview", use_container_width=True)
                with crop_cols[1]:
                    crop_w_px, crop_h_px = x2 - x1, y2 - y1
                    st.write(f"**Crop position:** left {x1}px, top {y1}px")
                    st.write(f"**Crop size:** {crop_w_px} × {crop_h_px} pixels")
                    if board_width_cm > 0:
                        st.write(f"**Estimated crop width:** {crop_w_px / image.width * board_width_cm:.3f} cm")
                    if board_height_cm > 0:
                        st.write(f"**Estimated crop height:** {crop_h_px / image.height * board_height_cm:.3f} cm")
                    if board_width_cm <= 0 and board_height_cm <= 0:
                        st.caption("Enter the real PCB width and/or height above to estimate crop dimensions in cm.")
                    if st.button("Inspect this drawn crop", key="use_workarea_crop", type="primary", use_container_width=True):
                        crop_client = new_client()
                        if crop_client is None:
                            st.error("Add GEMINI_API_KEY to Streamlit Secrets or the server environment before inspecting.")
                        else:
                            with st.spinner("Inspecting the selected work-area crop…"):
                                try:
                                    report, verifier = run_inspection(crop_client, model_name, roi, enhanced_review)
                                    st.session_state["inspection"] = report
                                    st.session_state["verifier"] = verifier
                                    st.session_state["report"] = {
                                        "application": APP_NAME,
                                        "image_filename": uploaded.name,
                                        "inspected_at_utc": datetime.now(timezone.utc).isoformat(),
                                        "joint_id": "drawn work-area crop",
                                        "crop_box_pixels": {"left": x1, "top": y1, "right": x2, "bottom": y2},
                                        "assessment": report,
                                        "second_review": verifier,
                                    }
                                    st.session_state["inspection_source"] = "drawn crop"
                                    st.success("Inspection complete. See the report below.")
                                except Exception as exc:
                                    st.error(f"Inspection failed: {str(exc)[:600]}")
            else:
                st.caption("No rectangle yet. Drag on the image to draw your work area.")
        except TypeError as exc:
            st.error("The crop drawing component failed to initialize. Update the drawable-canvas dependency and restart the app.")
            st.code(str(exc))
            st.caption("As a fallback, use the Manual crop selection controls below.")
        except Exception as exc:
            st.error("Could not open the interactive crop canvas.")
            st.code(f"{type(exc).__name__}: {exc}")
            st.caption("As a fallback, use the Manual crop selection controls below.")
    else:
        st.warning("Interactive crop drawing is unavailable. Install the updated requirements and restart the app.")
        st.caption("As a fallback, use the Manual crop selection controls below.")

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
        st.markdown("**Find solder-work candidates**")
        st.caption("Gemini proposes a tool-contact point and classifies it as SOLDER, DESOLDER, or INSPECT. Coordinates are estimated from your reference board dimensions above.")
        locate = st.button("Find candidate joints", type="primary", use_container_width=True)
        if locate:
            with st.spinner("Gemini is locating candidate solder-work points…"):
                try:
                    det = ask_vision(client, model_name, LOCATE_PROMPT, image)
                    joints = det.get("joints", [])
                    valid = []
                    for idx, j in enumerate(joints[:30], start=1):
                        b = j.get("box_2d")
                        try:
                            if not isinstance(b, list) or len(b) != 4:
                                continue
                            b = [max(0, min(1000, int(float(v)))) for v in b]
                            if b[2] <= b[0] or b[3] <= b[1]:
                                continue
                            point = j.get("point_2d")
                            if not isinstance(point, list) or len(point) != 2:
                                point = [(b[0] + b[2]) // 2, (b[1] + b[3]) // 2]
                            point = [max(0, min(1000, int(float(v)))) for v in point]
                            j["box_2d"] = b
                            j["point_2d"] = point
                            j["joint_id"] = idx
                            action = str(j.get("action", "INSPECT")).upper()
                            j["action"] = action if action in {"SOLDER", "DESOLDER", "INSPECT"} else "INSPECT"
                            conf = str(j.get("confidence", "low")).lower()
                            j["confidence"] = conf if conf in {"low", "medium", "high"} else "low"
                            valid.append(j)
                        except (ValueError, TypeError, OverflowError):
                            continue
                    det["joints"] = valid
                    st.session_state["detection"] = det
                    st.session_state.pop("inspection", None)
                    st.session_state.pop("verifier", None)
                except Exception as exc:
                    st.error(f"Could not locate joints: {str(exc)[:500]}")
        st.markdown("**Review candidates**")
        st.caption("Check each point against the image before using it. AI detections are suggestions, not machine commands.")

    detection = st.session_state.get("detection")
    if detection:
        joints = detection.get("joints", [])
        st.markdown("---")
        st.markdown('<div class="section-title">Candidate regions</div>', unsafe_allow_html=True)
        if joints:
            st.image(draw_candidate_boxes(image, joints), use_container_width=True)
            st.caption(detection.get("summary", "Review the boxes and action labels before choosing a candidate."))
            if detection.get("limitations"):
                for limitation in detection["limitations"]:
                    st.caption(f"Limitation: {limitation}")
            table_rows = []
            for j in joints:
                py_norm, px_norm = j["point_2d"]
                row = {
                    "Point": j["joint_id"],
                    "Action": j.get("action", "INSPECT"),
                    "Pixel X": round(px_norm * image.width / 1000),
                    "Pixel Y": round(py_norm * image.height / 1000),
                    "Confidence": j.get("confidence", "low"),
                    "Reason": j.get("reason", j.get("description", "")),
                }
                if board_width_cm > 0:
                    row["X (cm from top-left)"] = round(px_norm * board_width_cm / 1000, 3)
                else:
                    row["X (cm from top-left)"] = "Enter reference width"
                if board_height_cm > 0:
                    row["Y (cm from top-left)"] = round(py_norm * board_height_cm / 1000, 3)
                else:
                    row["Y (cm from top-left)"] = "Enter reference height"
                table_rows.append(row)
            st.markdown("#### Candidate coordinates and recommended action")
            st.caption("Origin is the top-left corner of the full uploaded image; X increases to the right and Y increases downward. Enter the measured width and height of the image/board above for centimetre coordinates.")
            st.dataframe(table_rows, use_container_width=True, hide_index=True)
            import csv
            csv_buffer = io.StringIO()
            csv_writer = csv.DictWriter(csv_buffer, fieldnames=list(table_rows[0].keys()))
            csv_writer.writeheader()
            csv_writer.writerows(table_rows)
            st.download_button("Download candidate coordinates (CSV)", data=csv_buffer.getvalue(), file_name="soldersight_candidate_coordinates.csv", mime="text/csv")
            st.warning("Human verification required: a photo may not reveal pad connectivity, hidden defects, or whether removal is safe. These are proposed locations only; no hardware commands are sent.")
            option_map = {}
            for idx,j in enumerate(joints):
                label = f"#{j['joint_id']} · {j.get('action', 'INSPECT')} · {j.get('description','Candidate region')[:75]}"
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
                st.write(f"**Proposed action:** {selected_joint.get('action', 'INSPECT')}")
                py_norm, px_norm = selected_joint["point_2d"]
                pixel_x = round(px_norm * image.width / 1000)
                pixel_y = round(py_norm * image.height / 1000)
                st.write(f"**Tool target (pixels):** X={pixel_x}, Y={pixel_y}")
                if board_width_cm > 0 and board_height_cm > 0:
                    st.write(f"**Tool target (cm from top-left):** X={px_norm*board_width_cm/1000:.3f} cm, Y={py_norm*board_height_cm/1000:.3f} cm")
                else:
                    st.warning("Enter both reference PCB dimensions above to calculate X/Y in centimetres.")
                st.write(f"**Reason:** {selected_joint.get('reason', 'No specific visual reason returned.')}")
                st.write(f"**Confidence:** {selected_joint.get('confidence', 'low').title()} · **Visibility:** {selected_joint.get('visibility','not specified').replace('_',' ').title()}")
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
            x = a.number_input("Left (px)", min_value=0, max_value=max(0,image.width-1), value=int(st.session_state.get("crop_box_px", (0, 0, max(1,image.width//4), max(1,image.height//4)))[0]), step=max(1,image.width//20))
            y = b.number_input("Top (px)", min_value=0, max_value=max(0,image.height-1), value=int(st.session_state.get("crop_box_px", (0, 0, max(1,image.width//4), max(1,image.height//4)))[1]), step=max(1,image.height//20))
            cw = c.number_input("Width (px)", min_value=1, max_value=image.width, value=max(1, min(image.width, int(st.session_state.get("crop_box_px", (0, 0, max(1,image.width//4), max(1,image.height//4)))[2] - st.session_state.get("crop_box_px", (0, 0, max(1,image.width//4), max(1,image.height//4)))[0]))), step=max(1,image.width//20))
            ch = d.number_input("Height (px)", min_value=1, max_value=image.height, value=max(1, min(image.height, int(st.session_state.get("crop_box_px", (0, 0, max(1,image.width//4), max(1,image.height//4)))[3] - st.session_state.get("crop_box_px", (0, 0, max(1,image.width//4), max(1,image.height//4)))[1]))), step=max(1,image.height//20))
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
