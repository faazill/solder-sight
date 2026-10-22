import io
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

import streamlit as st
from PIL import Image, ImageOps
from google import genai
from google.genai import types

APP_NAME = "SolderSight"
DEFAULT_MODEL = "gemini-3.8-flash"
MAX_IMAGE_MB = 12
MAX_DIMENSION = 1400
JPEG_QUALITY = 82

st.set_page_config(page_title="SolderSight Playground", page_icon="⌁", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap');
:root { --ink:#eaf0f5; --muted:#93a4b5; --line:#2b3947; --surface:#111a23; --panel:#17232e; --accent:#c9f36a; }
html, body, [class*="css"] { font-family:'Manrope',sans-serif; }
.stApp { background:radial-gradient(ellipse at 15% 0%, #1d2e3a 0%, #0d141b 48%, #0a1016 100%); color:var(--ink); }
.block-container {max-width:1500px;padding-top:1.2rem;padding-bottom:3rem;}
header[data-testid="stHeader"] {background:transparent;}
section[data-testid="stSidebar"] {background:#101922;border-right:1px solid #273541;}
section[data-testid="stSidebar"] * {color:#dce6ee;}
.brand {display:flex;align-items:center;gap:12px;margin-bottom:5px;}
.brand-mark {width:42px;height:42px;border-radius:13px;display:flex;align-items:center;justify-content:center;background:var(--accent);color:#101820;font-size:25px;font-weight:800;}
.brand-name {font-size:25px;font-weight:800;letter-spacing:-1px;color:#f2f6f9;line-height:1.1;}
.brand-sub {color:#91a3b3;font-size:12px;margin-top:4px;}
.topline {height:1px;background:linear-gradient(90deg,#394b58,transparent);margin:17px 0 25px;}
.eyebrow {font-family:'DM Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:1.8px;color:var(--accent);margin-bottom:9px;}
.hero-title {font-size:clamp(30px,4vw,48px);line-height:1.04;letter-spacing:-2px;font-weight:800;color:#f4f7f9;margin:0 0 12px;}
.hero-copy {font-size:14px;line-height:1.7;color:#a5b4c1;max-width:680px;}
.section-title {font-size:17px;font-weight:750;color:#edf3f7;margin:8px 0 3px;}
.section-help {font-size:12px;color:#92a4b4;margin-bottom:14px;line-height:1.6;}
.panel {background:linear-gradient(145deg,rgba(27,41,53,.94),rgba(17,27,36,.96));border:1px solid #2b3b49;border-radius:17px;padding:19px 20px;}
.pill {display:inline-block;border:1px solid #3c4d59;border-radius:99px;padding:5px 10px;font-family:'DM Mono',monospace;font-size:10px;color:#c6d2db;letter-spacing:.5px;}
div[data-testid="stMetric"] {border:1px solid #2b3b49;border-radius:13px;padding:12px 15px;background:#14212b;}
div[data-testid="stMetric"] label,div[data-testid="stMetric"] [data-testid="stMetricValue"] {color:#edf4f8;}
div.stButton > button, div[data-testid="stDownloadButton"] button {border-radius:10px;font-weight:750;min-height:43px;border:1px solid #3b4b58;}
div.stButton > button[kind="primary"] {background:var(--accent);color:#111a20;border:0;}
div.stButton > button[kind="primary"]:hover {background:#dcff91;color:#111a20;}
div[data-testid="stFileUploader"] {border:1px dashed #435461;border-radius:13px;padding:10px;background:#111c25;}
div[data-testid="stFileUploader"] section {background:transparent;}
[data-testid="stRadio"] label {color:#dce6ee;}
.stAlert {border-radius:12px;}
hr {border-color:#2b3b49;}
footer {visibility:hidden;}
</style>
<div class="brand"><div class="brand-mark">⌁</div><div><div class="brand-name">SolderSight</div><div class="brand-sub">VISION PLAYGROUND <span style="color:#c9f36a">/</span> PCB QUALITY LAB</div></div><div style="margin-left:auto"><span class="pill">EXPERIMENTAL · AI INSPECTION</span></div></div>
<div class="topline"></div>
<div class="eyebrow">01 / Visual inspection workspace</div>
<div class="hero-title">See the joint.<br>Understand the quality.</div>
<div class="hero-copy">A fast, visual playground for reviewing PCB solder joints. Capture a live photo or upload an image, then run an evidence-based AI assessment in one step.</div>
<div style="height:22px"></div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### PLAYGROUND SETTINGS")
    model_name = st.text_input("Analysis model", value=DEFAULT_MODEL, help="Use a vision-capable model enabled for your API project.").strip() or DEFAULT_MODEL
    enhanced_review = st.toggle("Enhanced second review (slower)", value=False, help="Runs an optional second AI request for consistency checking. Turn off for the fastest single-request result.")
    st.markdown("---")
    st.markdown("**Capture checklist**\n- Fill the frame with the joint.\n- Hold the camera steady and focus.\n- Avoid glare and harsh reflections.\n- Include nearby pads where possible.")
    st.markdown("---")
    with st.expander("Privacy & system information"):
        st.write("Images selected for analysis are sent to the configured external vision API. Do not upload confidential board images unless your data policy permits it. SolderSight uses a third-party vision API behind the scenes.")
        st.caption("Visual AI assistance only. It cannot prove electrical continuity, hidden defects, or mechanical strength.")


def get_api_key() -> str | None:
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        key = ""
    return key or os.environ.get("GEMINI_API_KEY")


def new_client():
    key = get_api_key()
    return genai.Client(api_key=key) if key else None


def normalize_image(img: Image.Image) -> Image.Image:
    """Normalize orientation, resize before upload, and strip metadata via RGB conversion."""
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
    return img


def encode_jpeg(img: Image.Image) -> bytes:
    """Compress image in memory so only the resized JPEG is sent to the vision API."""
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return buffer.getvalue()


def parse_json_response(text: str) -> dict[str, Any]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.I)
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


INSPECT_PROMPT = """
You are a careful visual quality-review assistant for PCB solder joints. Inspect the supplied full image in ONE pass. Assess the visible solder joint(s) directly; do not first perform a separate detection step. If multiple joints are visible, summarize the overall visible quality and list individual visible concerns where possible. Do not assume electrical continuity or hidden mechanical integrity.

Return JSON only with this schema:
{
 "joint_status":"completed|in_progress|unclear",
 "quality":"good|defective|uncertain",
 "recommendation":"accept|resolder|inspect_further|finish_then_inspect",
 "defects":[{"name":"short defect name","evidence":"specific visible evidence","severity":"minor|moderate|major"}],
 "description":"plain-language description of solder shape, coverage, wetting appearance and relation to neighboring pads; note if multiple joints are shown",
 "reason":"why the recommendation follows from the visible evidence",
 "confidence":"low|medium|high",
 "image_quality":{"focus":"good|adequate|poor","lighting":"good|adequate|poor","occlusion":"none|partial|major"},
 "limitations":[]
}

Rules:
- Use only visible evidence; do not infer unseen facts.
- A bright or shiny surface alone does not prove quality.
- Call a solder bridge only if solder visibly connects separate pads/pins.
- Excess solder needs visible evidence such as a large uncontrolled mound or bridging. Insufficient solder needs visible lack of coverage/contact, not merely a small-looking joint.
- A soldering iron touching the joint, molten solder, or an unfinished process means joint_status=in_progress and recommendation=finish_then_inspect.
- If blur, glare, occlusion, image scale or ambiguous geometry prevents assessment, use quality=uncertain and recommendation=inspect_further.
- Use recommendation=resolder only when a visible defect supports rework.
- Use recommendation=accept only when the joint(s) appear completed, adequately visible, and no obvious defect is apparent.
- Keep confidence conservative. Do not output numerical accuracy or pretend confidence is a calibrated probability.
- If the photo is too wide or the joints are too small to assess reliably, say so and recommend a closer photo rather than guessing.
"""

VERIFY_PROMPT = """
Independently review this same PCB solder image for quality-control consistency. Return JSON only:
{"review_quality":"good|defective|uncertain","review_recommendation":"accept|resolder|inspect_further|finish_then_inspect","agreement":"agree|partly_agree|disagree","missed_concerns":[],"review_note":"short evidence-based note"}
Use conservative visual rules: no claims about hidden defects or electrical continuity; an iron touching/molten solder means finish_then_inspect; uncertain visibility means inspect_further. Do not simply agree with the prior answer. Prior assessment:
"""


def ask_vision(client, model: str, prompt: str, img: Image.Image) -> dict[str, Any]:
    payload = encode_jpeg(img)
    response = client.models.generate_content(
        model=model,
        contents=[prompt, types.Part.from_bytes(data=payload, mime_type="image/jpeg")],
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1),
    )
    return parse_json_response(response.text)


def run_inspection(client, model, image, enhanced):
    report = ask_vision(client, model, INSPECT_PROMPT, image)
    verifier = None
    if enhanced:
        try:
            verifier = ask_vision(client, model, VERIFY_PROMPT + json.dumps(report, ensure_ascii=False), image)
            if verifier.get("agreement") in ("disagree", "partly_agree") and report.get("recommendation") == "accept":
                report["quality"] = "uncertain"
                report["recommendation"] = "inspect_further"
                report.setdefault("limitations", []).append("The independent review raised uncertainty; verify manually.")
        except Exception as exc:
            verifier = {"agreement": "unavailable", "review_note": f"Second review unavailable: {str(exc)[:200]}"}
    return report, verifier


def status_banner(recommendation):
    if recommendation == "accept":
        st.success("ACCEPT · No obvious visual defect identified")
    elif recommendation == "resolder":
        st.error("REWORK RECOMMENDED · A visible defect may require resoldering")
    elif recommendation == "finish_then_inspect":
        st.warning("FINISH SOLDERING · Reinspect after the iron is removed and the joint cools")
    else:
        st.warning("INSPECT FURTHER · The image does not support a confident decision")


st.markdown('<div class="eyebrow">02 / Input source</div><div class="section-title">Start a new inspection</div><div class="section-help">Choose your input mode. Captured and uploaded images use the same optimized analysis pipeline.</div>', unsafe_allow_html=True)
source = st.radio("Image source", ["Upload image", "Live camera"], horizontal=True, label_visibility="collapsed")
uploaded = None
if source == "Upload image":
    uploaded = st.file_uploader("Choose a PCB or solder-joint image", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=False, help=f"PNG, JPG or WEBP · source file limit {MAX_IMAGE_MB} MB")
else:
    uploaded = st.camera_input("Take a photo of the solder joints")

if uploaded is not None:
    if uploaded.size > MAX_IMAGE_MB * 1024 * 1024:
        st.error(f"Image exceeds {MAX_IMAGE_MB} MB. Please choose a smaller image.")
        st.stop()
    try:
        original = Image.open(uploaded)
        image = normalize_image(original)
        jpeg_bytes = encode_jpeg(image)
    except Exception:
        st.error("This image could not be opened. Try a standard PNG or JPEG.")
        st.stop()

    image_key = f"{getattr(uploaded, 'name', 'camera')}:{uploaded.size}:{hash(jpeg_bytes)}"
    if st.session_state.get("image_key") != image_key:
        st.session_state["image_key"] = image_key
        st.session_state.pop("inspection", None)
        st.session_state.pop("verifier", None)
        st.session_state.pop("report", None)

    left, right = st.columns([1.1, 0.9], gap="large")
    with left:
        st.markdown('<div class="eyebrow">INPUT / 01</div><div class="section-title">Image canvas</div><div class="section-help">Preview the frame before sending it for analysis.</div>', unsafe_allow_html=True)
        st.image(image, use_container_width=True)
    with right:
        st.markdown('<div class="eyebrow">PAYLOAD / 02</div><div class="section-title">Ready to analyze</div><div class="section-help">Image is normalized locally before API submission.</div>', unsafe_allow_html=True)
        a, b = st.columns(2)
        a.metric("Working resolution", f"{image.width} × {image.height}")
        b.metric("Compressed size", f"{len(jpeg_bytes) / 1024:.0f} KB")
        st.caption(f"Resized to max {MAX_DIMENSION}px on the longest side and JPEG-compressed before analysis.")
        analyze = st.button("Analyze Solder Quality", type="primary", use_container_width=True)

    if analyze:
        client = new_client()
        if client is None:
            st.error("Inspection is not configured yet. Add GEMINI_API_KEY to Streamlit Secrets or the server environment.")
            st.code('GEMINI_API_KEY = "your_api_key"', language="toml")
        else:
            with st.spinner("Analyzing solder quality…"):
                try:
                    report, verifier = run_inspection(client, model_name, image, enhanced_review)
                    st.session_state["inspection"] = report
                    st.session_state["verifier"] = verifier
                    st.session_state["report"] = {
                        "application": APP_NAME,
                        "image_filename": getattr(uploaded, "name", "camera_capture.jpg"),
                        "inspected_at_utc": datetime.now(timezone.utc).isoformat(),
                        "image_resolution": {"width": image.width, "height": image.height},
                        "assessment": report,
                        "second_review": verifier,
                    }
                    history_item = {
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "quality": str(report.get("quality", "uncertain")).title(),
                        "recommendation": str(report.get("recommendation", "inspect_further")).replace("_", " ").title(),
                    }
                    history = st.session_state.get("inspection_history", [])
                    if not history or history[0].get("time") != history_item["time"]:
                        st.session_state["inspection_history"] = [history_item] + history[:7]
                except Exception as exc:
                    st.error(f"Inspection failed: {str(exc)[:500]}")

with st.sidebar:
    st.markdown("---")
    st.markdown("### RECENT RUNS")
    history = st.session_state.get("inspection_history", [])
    if history:
        for item in history[:6]:
            st.markdown(f"**{item['quality']}** · {item['recommendation']}  ")
            st.caption(f"{item['time']} · Visual inspection")
    else:
        st.caption("Your inspection history will appear here after the first run.")

report = st.session_state.get("inspection")
if report:
    st.markdown("---")
    st.markdown('<div class="eyebrow">OUTPUT / 03</div><div class="section-title">Inspection results</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-help">Review the visible evidence and recommended action. This is visual decision support, not a certification.</div>', unsafe_allow_html=True)
    status_banner(report.get("recommendation", "inspect_further"))
    m1, m2, m3 = st.columns(3)
    m1.metric("Visual assessment", str(report.get("quality", "uncertain")).replace("_", " ").title())
    m2.metric("Joint status", str(report.get("joint_status", "unclear")).replace("_", " ").title())
    m3.metric("Confidence", str(report.get("confidence", "low")).title())
    st.markdown("#### Description")
    st.write(report.get("description", "No description provided."))
    st.markdown("#### Visible findings")
    defects = report.get("defects", [])
    if defects:
        for defect in defects:
            if isinstance(defect, dict):
                st.markdown(f"**{defect.get('name', 'Finding')}** · {str(defect.get('severity', 'unspecified')).title()}")
                st.write(defect.get("evidence", ""))
            else:
                st.write(f"- {defect}")
    else:
        st.write("No specific visible defect was reported. This is not proof that the joint is defect-free.")
    st.markdown("#### Why this action was recommended")
    st.write(report.get("reason", ""))
    iq = report.get("image_quality", {})
    with st.expander("Image quality and limitations"):
        st.write(f"**Focus:** {str(iq.get('focus', 'not assessed')).title()}")
        st.write(f"**Lighting:** {str(iq.get('lighting', 'not assessed')).title()}")
        st.write(f"**Occlusion:** {str(iq.get('occlusion', 'not assessed')).title()}")
        for item in report.get("limitations", []):
            st.write(f"- {item}")
    verifier = st.session_state.get("verifier")
    if enhanced_review and verifier:
        with st.expander("Consistency review"):
            st.write("**Agreement:**", str(verifier.get("agreement", "unavailable")).replace("_", " ").title())
            st.write(verifier.get("review_note", ""))
            for concern in verifier.get("missed_concerns", []):
                st.write(f"- {concern}")
    st.download_button("Download inspection report (JSON)", data=json.dumps(st.session_state.get("report", report), indent=2, ensure_ascii=False), file_name="soldersight_inspection_report.json", mime="application/json", type="primary")
    st.caption("Important: visual analysis cannot confirm electrical continuity, hidden defects, or mechanical strength. Verify critical joints using appropriate inspection methods.")
else:
    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("#### 1. Capture or upload")
        st.write("Choose an existing image or take a photo with your camera.")
    with c2:
        st.markdown("#### 2. Optimize")
        st.write("Orientation, resizing and JPEG compression happen automatically before analysis.")
    with c3:
        st.markdown("#### 3. Inspect")
        st.write("One AI request returns visible findings, quality and a recommended action.")
