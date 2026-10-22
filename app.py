import io
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

import streamlit as st
from PIL import Image, ImageDraw, ImageOps
from google import genai
from google.genai import types

APP_NAME = "SolderSight"
DEFAULT_MODEL = "gemini-3.8-flash"
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
        "Analysis model",
        value=DEFAULT_MODEL,
        help="Uses a vision-capable model available to your API project."
    ).strip() or DEFAULT_MODEL
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

def ask_vision(client, model: str, prompt: str, img: Image.Image) -> dict[str, Any]:
    response = client.models.generate_content(
        model=model,
        contents=[prompt, as_part(img)],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )
    return parse_json_response(response.text)

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
        for key in ["detection","inspection","verifier","crop","selected_label","report"]:
            st.session_state.pop(key, None)
        st.session_state["image_key"] = image_key
        st.session_state["source_filename"] = uploaded.name

    info1, info2, info3 = st.columns(3)
    info1.metric("Image", uploaded.name[:26] + ("…" if len(uploaded.name)>26 else ""))
    info2.metric("Working resolution", f"{image.width} × {image.height}")
    info3.metric("File size", f"{uploaded.size/1024:.0f} KB")

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
