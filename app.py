import io
import json
import os
import random
import re
import time
from datetime import datetime, timezone
from typing import Any

import streamlit as st
from PIL import Image, ImageOps
from google import genai
from google.genai import types

APP_NAME = "SolderSight"
DEFAULT_MODEL = "gemini-2.5-flash"
FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash"]
MAX_DIMENSION = 1400
JPEG_QUALITY = 82
MAX_RETRIES = 3

st.set_page_config(
    page_title="SolderSight | Solder Inspection Playground",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
:root { color-scheme: light; }
.stApp { background: #f6f8fb; color: #172033; }
.block-container { max-width: 1480px; padding-top: 1.4rem; padding-bottom: 3rem; }
header[data-testid="stHeader"] { background: rgba(246,248,251,.92); }
section[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #e4e9f1; }
section[data-testid="stSidebar"] > div { padding-top: 1.5rem; }
.brand { display:flex; align-items:center; gap:12px; }
.brand-mark { width:44px; height:44px; display:flex; align-items:center; justify-content:center;
  border-radius:14px; color:#fff; background:linear-gradient(135deg,#2558d9,#6c8df0); font-size:23px; }
.brand-name { font-size:28px; line-height:1.1; letter-spacing:-.8px; font-weight:800; color:#172033; }
.brand-sub { color:#748096; font-size:13px; margin-top:5px; }
.hero { background:linear-gradient(120deg,#ffffff 0%,#edf3ff 100%); border:1px solid #e1e8f7;
  border-radius:22px; padding:26px 28px; margin:12px 0 22px; }
.hero-kicker { font-size:11px; text-transform:uppercase; letter-spacing:1.6px; color:#4168c8; font-weight:800; }
.hero-title { font-size:30px; line-height:1.15; letter-spacing:-1px; font-weight:800; color:#172033; margin:8px 0; }
.hero-copy { color:#66738a; font-size:14px; max-width:740px; }
.panel { background:#fff; border:1px solid #e3e8f0; border-radius:18px; padding:20px; }
.panel-title { font-size:17px; font-weight:750; color:#172033; margin-bottom:4px; }
.panel-sub { font-size:12px; color:#7a869a; margin-bottom:15px; }
.pill { display:inline-block; border-radius:999px; padding:5px 10px; font-size:11px; font-weight:700;
  color:#315dc4; background:#edf2ff; border:1px solid #dbe5ff; }
div.stButton > button, div[data-testid="stDownloadButton"] button {
  border-radius:11px; min-height:44px; font-weight:700; border:1px solid #dce3ed; }
div.stButton > button[kind="primary"] { background:#315fdb; border-color:#315fdb; color:white; }
div[data-testid="stFileUploader"] { border:1px dashed #b9c6d9; border-radius:13px; padding:12px; background:#fbfcfe; }
div[data-testid="stCameraInput"] { border-radius:14px; overflow:hidden; }
div[data-testid="stMetric"] { background:#fff; border:1px solid #e5eaf2; border-radius:14px; padding:14px; }
hr { border-color:#e6ebf2; }
.small-note { color:#78849a; font-size:12px; }
footer { visibility:hidden; }
</style>
<div class="brand">
  <div class="brand-mark">⌁</div>
  <div>
    <div class="brand-name">SolderSight</div>
    <div class="brand-sub">AI solder inspection · Playground</div>
  </div>
  <div style="margin-left:auto"><span class="pill">VISION LAB · DEMO</span></div>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### Workspace")
    st.caption("Configure your inspection session.")
    source = st.radio("Image source", ["Upload image", "Live camera"], horizontal=False)
    model_name = st.text_input(
        "Primary vision model",
        value=os.environ.get("SOLDERSIGHT_MODEL", DEFAULT_MODEL),
        help="Use an image-capable Gemini model enabled for your API project."
    ).strip() or DEFAULT_MODEL
    enable_fallback = st.toggle("Try fallback models on overload", value=True)
    enhanced_review = st.toggle(
        "Second opinion (slower)", value=False,
        help="Makes an extra API request. Leave off for the fastest workflow."
    )
    st.divider()
    st.markdown("**Capture tips**")
    st.caption("• Keep the joint in focus\n\n• Avoid glare and deep shadows\n\n• Include adjacent pads when checking for bridges\n\n• Capture after the iron is removed")
    st.divider()
    with st.expander("Privacy & limitations"):
        st.write("Images selected for analysis are sent to the configured third-party vision API. Do not upload confidential board images unless permitted.")
        st.caption("Visual assistance only; this cannot confirm electrical continuity, hidden defects, or mechanical strength.")

st.markdown("""
<div class="hero">
  <div class="hero-kicker">Inspection workspace</div>
  <div class="hero-title">See the joint. Understand the quality.</div>
  <div class="hero-copy">Upload a PCB photo or capture one from your camera. SolderSight optimizes the image before analysis and returns evidence-based findings with a recommended next step.</div>
</div>
""", unsafe_allow_html=True)

def get_api_key() -> str | None:
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        key = ""
    return key or os.environ.get("GEMINI_API_KEY")

def make_client():
    key = get_api_key()
    return genai.Client(api_key=key) if key else None

def normalize_image(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
    return img

def optimized_jpeg_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return buf.getvalue()

def image_part(img: Image.Image):
    return types.Part.from_bytes(data=optimized_jpeg_bytes(img), mime_type="image/jpeg")

def parse_json_response(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise ValueError("The model returned an unreadable response. Please retry.")
        result = json.loads(match.group(0))
    if not isinstance(result, dict):
        raise ValueError("Unexpected response format from the model.")
    return result

INSPECT_PROMPT = """
You are a careful visual quality-review assistant for PCB solder joints. Assess the supplied image directly.
Use only visible evidence. Do not claim electrical continuity, hidden defects, internal wetting, or mechanical strength.
A shiny surface alone does not prove quality. Call a solder bridge only if solder visibly connects separate pads/pins.
If blur, glare, occlusion, scale, or ambiguous geometry prevents assessment, mark quality uncertain and recommend inspect_further.
If soldering is active, molten, or unfinished, mark joint_status=in_progress and recommendation=finish_then_inspect.
Recommend resolder only when a visible defect supports rework. Recommend accept only when completed, sufficiently visible, and no obvious defect is apparent.
Return JSON only in this schema:
{
 "joint_status":"completed|in_progress|unclear",
 "quality":"good|defective|uncertain",
 "recommendation":"accept|resolder|inspect_further|finish_then_inspect",
 "defects":[{"name":"short defect name","evidence":"specific visible evidence","severity":"minor|moderate|major"}],
 "description":"plain-language description of solder shape, coverage, visible wetting appearance and neighboring pads",
 "reason":"why the recommendation follows from visible evidence",
 "confidence":"low|medium|high",
 "image_quality":{"focus":"good|adequate|poor","lighting":"good|adequate|poor","occlusion":"none|partial|major"},
 "limitations":[]
}
If the photo shows multiple joints, explain that in description and avoid implying each joint was individually verified.
"""

VERIFY_PROMPT = """
Independently review the supplied solder-joint photo and prior assessment. Return JSON only:
{"review_quality":"good|defective|uncertain","review_recommendation":"accept|resolder|inspect_further|finish_then_inspect","agreement":"agree|partly_agree|disagree","missed_concerns":[],"review_note":"short evidence-based note"}
Do not claim hidden defects or electrical continuity. Prior assessment:
"""

def is_transient_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(term in msg for term in (
        "503", "unavailable", "high demand", "429", "resource_exhausted",
        "rate limit", "500", "502", "504", "deadline", "temporarily",
        "internal error", "service unavailable"
    ))

def is_rate_or_overload(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(term in msg for term in ("503", "unavailable", "high demand", "429", "resource_exhausted", "rate limit"))

def call_model_with_retry(client, model: str, prompt: str, img: Image.Image, attempts: int = MAX_RETRIES):
    """Retry transient service errors with exponential backoff and jitter."""
    last_exc = None
    for attempt in range(attempts + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[prompt, image_part(img)],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            return parse_json_response(response.text), model
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts or not is_transient_error(exc):
                raise
            delay = min(8.0, 1.25 * (2 ** attempt)) + random.uniform(0.0, 0.65)
            st.warning(f"AI service is busy. Retrying automatically in {delay:.1f} seconds ({attempt + 1}/{attempts})…")
            time.sleep(delay)
    raise last_exc

def ask_with_fallback(client, selected_model: str, prompt: str, img: Image.Image, fallback_enabled: bool):
    models = [selected_model]
    if fallback_enabled:
        for candidate in FALLBACK_MODELS:
            if candidate not in models:
                models.append(candidate)
    last_exc = None
    for idx, model in enumerate(models):
        try:
            data, used_model = call_model_with_retry(client, model, prompt, img)
            return data, used_model
        except Exception as exc:
            last_exc = exc
            if idx < len(models) - 1 and is_rate_or_overload(exc):
                st.warning(f"{model} remains unavailable after retries. Trying fallback model {models[idx + 1]}…")
                continue
            if idx < len(models) - 1 and not is_transient_error(exc):
                # Do not mask invalid-key / permission / malformed-request problems with fallback attempts.
                raise
    raise last_exc

def run_inspection(client, selected_model, image, fallback_enabled, second_opinion):
    report, used_model = ask_with_fallback(client, selected_model, INSPECT_PROMPT, image, fallback_enabled)
    verifier = None
    if second_opinion:
        try:
            verifier, _ = ask_with_fallback(
                client, selected_model, VERIFY_PROMPT + json.dumps(report, ensure_ascii=False),
                image, fallback_enabled
            )
            if verifier.get("agreement") == "disagree":
                report["quality"] = "uncertain"
                report["recommendation"] = "inspect_further"
                report.setdefault("limitations", []).append(
                    "The independent review disagreed with the first assessment; manual inspection is recommended."
                )
            elif verifier.get("agreement") == "partly_agree" and report.get("recommendation") == "accept":
                report["quality"] = "uncertain"
                report["recommendation"] = "inspect_further"
                report.setdefault("limitations", []).append(
                    "The independent review raised uncertainty; verify manually."
                )
        except Exception as exc:
            verifier = {"agreement": "unavailable", "review_note": f"Second opinion unavailable: {str(exc)[:240]}"}
    return report, verifier, used_model

def status_banner(recommendation):
    if recommendation == "accept":
        st.success("ACCEPT · No obvious visual defect identified")
    elif recommendation == "resolder":
        st.error("REWORK RECOMMENDED · A visible defect may require resoldering")
    elif recommendation == "finish_then_inspect":
        st.warning("FINISH SOLDERING · Reinspect after the joint cools")
    else:
        st.warning("INSPECT FURTHER · The image does not support a confident decision")

def render_report(report: dict, verifier, metadata: dict):
    status_banner(report.get("recommendation", "inspect_further"))
    a, b, c = st.columns(3)
    a.metric("Visual quality", report.get("quality", "uncertain").replace("_", " ").title())
    b.metric("Joint status", report.get("joint_status", "unclear").replace("_", " ").title())
    c.metric("Confidence", report.get("confidence", "low").title())
    left, right = st.columns([1.15, 0.85], gap="large")
    with left:
        st.markdown("#### Visual findings")
        st.write(report.get("description", "No description provided."))
        defects = report.get("defects", [])
        if defects:
            for defect in defects:
                if isinstance(defect, dict):
                    st.markdown(f"**{defect.get('name', 'Finding')}** · {str(defect.get('severity', 'unspecified')).title()}")
                    st.caption(defect.get("evidence", ""))
                else:
                    st.write(f"• {defect}")
        else:
            st.info("No specific visible defect was reported. This is not proof that the joint is defect-free.")
    with right:
        st.markdown("#### Recommended action")
        st.write(report.get("reason", ""))
        iq = report.get("image_quality", {})
        st.markdown("#### Image quality")
        q1, q2, q3 = st.columns(3)
        q1.caption("Focus")
        q1.write(str(iq.get("focus", "—")).title())
        q2.caption("Lighting")
        q2.write(str(iq.get("lighting", "—")).title())
        q3.caption("Occlusion")
        q3.write(str(iq.get("occlusion", "—")).title())
        for item in report.get("limitations", []):
            st.caption(f"• {item}")
    if verifier:
        with st.expander("Second opinion"):
            st.write(f"**Agreement:** {str(verifier.get('agreement', 'unavailable')).replace('_', ' ').title()}")
            st.write(verifier.get("review_note", ""))
            for concern in verifier.get("missed_concerns", []):
                st.write(f"• {concern}")
    payload = {
        "application": APP_NAME,
        "inspected_at_utc": datetime.now(timezone.utc).isoformat(),
        **metadata,
        "assessment": report,
        "second_review": verifier,
    }
    st.download_button(
        "Download inspection report (JSON)",
        data=json.dumps(payload, indent=2, ensure_ascii=False),
        file_name="soldersight_inspection_report.json",
        mime="application/json",
        type="primary",
    )
    st.caption("Visual decision support only. Verify critical joints using appropriate inspection methods.")

# Source input and preview
source_col, preview_col = st.columns([0.9, 1.1], gap="large")
image = None
source_name = "captured_image.jpg"
with source_col:
    st.markdown('<div class="panel"><div class="panel-title">01 · Add an image</div><div class="panel-sub">Choose a source, then capture or upload a clear close-up.</div>', unsafe_allow_html=True)
    if source == "Upload image":
        uploaded = st.file_uploader("PCB or solder-joint photo", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=False)
        if uploaded is not None:
            source_name = uploaded.name
            if uploaded.size > 20 * 1024 * 1024:
                st.error("This file is larger than 20 MB. Please choose a smaller image.")
            else:
                try:
                    image = normalize_image(Image.open(uploaded))
                except Exception:
                    st.error("Could not open this image. Please try a standard JPG or PNG.")
    else:
        camera_file = st.camera_input("Capture solder joint")
        if camera_file is not None:
            source_name = "camera_capture.jpg"
            try:
                image = normalize_image(Image.open(camera_file))
            except Exception:
                st.error("Could not read the camera image. Please capture it again.")
    if image is not None:
        st.caption(f"Optimized working size: {image.width} × {image.height} px")
        st.caption(f"Estimated upload size: {len(optimized_jpeg_bytes(image)) / 1024:.0f} KB")
    st.markdown('</div>', unsafe_allow_html=True)

with preview_col:
    st.markdown('<div class="panel"><div class="panel-title">02 · Preview</div><div class="panel-sub">Check focus, lighting, and visibility before analysis.</div>', unsafe_allow_html=True)
    if image is not None:
        st.image(image, use_container_width=True)
    else:
        st.markdown("""
        <div style="height:270px;border:1px dashed #cbd5e3;border-radius:14px;background:#fafcff;display:flex;align-items:center;justify-content:center;text-align:center;padding:24px;color:#8995a8">
        <div><div style="font-size:36px;margin-bottom:8px">◎</div><b>No image selected</b><br><span style="font-size:13px">Your captured or uploaded image will appear here.</span></div>
        </div>
        """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("")
run_col, help_col = st.columns([0.34, 0.66], gap="medium")
with run_col:
    analyze_clicked = st.button("✦  Analyze solder quality", type="primary", use_container_width=True, disabled=image is None)
with help_col:
    st.markdown('<div class="small-note" style="padding-top:13px">One initial AI request by default. If the provider is overloaded, SolderSight retries and can switch to a fallback model automatically.</div>', unsafe_allow_html=True)

if analyze_clicked and image is not None:
    client = make_client()
    if client is None:
        st.error("API key not configured. Add GEMINI_API_KEY to Streamlit Secrets or the server environment.")
        st.code('GEMINI_API_KEY = "your_api_key"', language="toml")
    else:
        with st.status("Preparing image and connecting to the vision model…", expanded=True) as status:
            try:
                st.write("Image normalized and compressed.")
                st.write("Submitting quality assessment…")
                report, verifier, used_model = run_inspection(
                    client, model_name, image, enable_fallback, enhanced_review
                )
                st.session_state["last_result"] = {
                    "report": report,
                    "verifier": verifier,
                    "metadata": {
                        "image_filename": source_name,
                        "model_used": used_model,
                        "working_resolution": f"{image.width}x{image.height}",
                    },
                    "image": image,
                }
                status.update(label="Inspection complete", state="complete", expanded=False)
            except Exception as exc:
                status.update(label="Inspection could not be completed", state="error", expanded=True)
                msg = str(exc)
                low = msg.lower()
                if is_transient_error(exc):
                    st.error("The vision service is temporarily busy. Your image is still selected; click Analyze solder quality to retry in a moment.")
                    st.caption("Automatic retries and fallback models were attempted where applicable.")
                elif any(x in low for x in ("api key", "permission", "unauthorized", "403", "401")):
                    st.error("The API key may be invalid or lack permission for this model. Check GEMINI_API_KEY and the model access settings.")
                elif "404" in low or "not found" in low:
                    st.error("The selected model may not be available to your API project. Choose an enabled image-capable Gemini model in the sidebar.")
                else:
                    st.error(f"Inspection failed: {msg[:500]}")

result = st.session_state.get("last_result")
if result:
    st.markdown("---")
    st.markdown("### Inspection report")
    st.caption(f"Source: {result['metadata'].get('image_filename', 'image')} · Model: {result['metadata'].get('model_used', 'unknown')}")
    render_report(result["report"], result["verifier"], result["metadata"])

st.markdown("---")
st.markdown('<div class="small-note">SolderSight Playground · AI-assisted visual review, not a certified industrial inspection system.</div>', unsafe_allow_html=True)
