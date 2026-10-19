import io
import json
import os
from typing import Any

import streamlit as st
from PIL import Image, ImageDraw
from google import genai
from google.genai import types

APP_TITLE = "SolderSight | AI Solder Inspection"
DEFAULT_MODEL = "gemini-3.8-flash"
MAX_UPLOAD_MB = 12

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🔬",
    layout="wide",
)

st.markdown("""
<style>
.block-container {max-width: 1250px; padding-top: 2rem;}
.hero {padding: 1.4rem 1.6rem; border: 1px solid #26364a; border-radius: 18px;
       background: linear-gradient(135deg, #101b2b, #17283a); margin-bottom: 1rem;}
.hero h1 {margin: 0; color: #f4f8ff; font-size: 2.1rem;}
.hero p {color: #bdcbe0; margin: .45rem 0 0 0;}
.small-muted {color: #718096; font-size: .9rem;}
</style>
<div class="hero">
  <h1>🔬 SolderSight</h1>
  <p>Upload a PCB image, choose the solder joint, and get an AI-assisted visual quality assessment.</p>
</div>
""", unsafe_allow_html=True)

st.warning(
    "Prototype only: this is a visual aid, not a certified inspection system. "
    "Do not use its result alone to control production equipment or certify electrical reliability."
)

def get_api_key() -> str | None:
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        key = ""
    return key or os.environ.get("GEMINI_API_KEY")

def make_client():
    key = get_api_key()
    if not key:
        return None
    return genai.Client(api_key=key)

def image_part(img: Image.Image):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=92)
    return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")

def call_gemini(client, prompt: str, img: Image.Image) -> dict[str, Any]:
    response = client.models.generate_content(
        model=DEFAULT_MODEL,
        contents=[prompt, image_part(img)],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )
    text = response.text or ""
    # Defensive parse if the model wraps JSON in fences.
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0].strip()
    return json.loads(text)

DETECT_PROMPT = """
You are locating visible PCB solder joints for later close-up inspection.
Return JSON only with this exact structure:
{
 "overall_assessment": "short observation",
 "joints": [
   {
     "joint_id": 1,
     "box_2d": [ymin, xmin, ymax, xmax],
     "description": "short description of the region",
     "inspectable": true
   }
 ],
 "limitations": []
}
Coordinates are normalized integers 0-1000 in [ymin,xmin,ymax,xmax] order,
relative to the full image. Include only plausible solder joints/pads, not the
soldering iron, fingers, flux pot, wire spool, resistors, or unrelated objects.
Do not claim that visual inspection proves electrical continuity. If no joints
can be reliably located, return an empty joints list. If a joint is obscured or
being actively soldered, it may still be listed but set inspectable=false.
Limit the response to at most 20 likely joints. Be conservative and do not invent
coordinates.
"""

INSPECT_PROMPT = """
You are an assistant for visual PCB solder-joint inspection. Assess ONLY the
selected crop. The crop may include neighboring pads for context.

Return JSON only using:
{
 "joint_status": "completed | in_progress | unclear",
 "quality": "good | defective | uncertain",
 "defects": [],
 "description": "clear description of visible solder shape, coverage and surface",
 "recommendation": "accept | resolder | inspect_further | finish_then_inspect",
 "reason": "why this action is recommended",
 "confidence": "low | medium | high",
 "limitations": []
}

Check visible evidence for excess solder, insufficient solder, bridging between
adjacent pads, spikes, poor wetting/irregular coverage, or a disturbed joint.
Do not infer hidden defects, electrical continuity, or mechanical strength.
Do not call a bridge unless solder visibly connects separate pads.
A soldering iron touching the joint, molten solder, or an unfinished process
means joint_status=in_progress and recommendation=finish_then_inspect.
If the image is blurred, occluded, too small, or ambiguous, use uncertain and
inspect_further. Recommend resolder only when a visible defect supports it.
A shiny surface alone does not prove a good joint. Explain specific visual
evidence rather than guessing. This is an AI visual opinion, not a certification.
"""

def box_to_pixels(box, width, height, padding=0.12):
    ymin, xmin, ymax, xmax = box
    x1 = xmin / 1000 * width
    y1 = ymin / 1000 * height
    x2 = xmax / 1000 * width
    y2 = ymax / 1000 * height
    px = (x2 - x1) * padding
    py = (y2 - y1) * padding
    return (
        max(0, int(x1 - px)),
        max(0, int(y1 - py)),
        min(width, int(x2 + px)),
        min(height, int(y2 + py)),
    )

def draw_boxes(img, joints):
    out = img.copy().convert("RGB")
    draw = ImageDraw.Draw(out)
    w, h = out.size
    for joint in joints:
        try:
            x1, y1, x2, y2 = box_to_pixels(joint["box_2d"], w, h, padding=0)
            label = f"Joint {joint.get('joint_id', '?')}"
            draw.rectangle((x1, y1, x2, y2), outline="#00E5FF", width=max(3, w // 500))
            draw.rectangle((x1, max(0, y1-25), x1+110, y1), fill="#003B49")
            draw.text((x1+4, max(0, y1-22)), label, fill="white")
        except Exception:
            continue
    return out

with st.sidebar:
    st.subheader("Settings")
    model_name = st.text_input("Gemini model", value=DEFAULT_MODEL, help="Defaults to gemini-3.8-flash. Change only if your API account uses another available model.")
    st.caption("API key is read from Streamlit Secrets or the GEMINI_API_KEY environment variable. It is never requested from other visitors or shown in the UI.")
    st.divider()
    st.caption("Recommended image: completed joint, close-up, good lighting, camera focused on the pads.")

if model_name != DEFAULT_MODEL:
    DEFAULT_MODEL = model_name.strip()

uploaded = st.file_uploader(
    "Upload a PCB / solder-joint image",
    type=["png", "jpg", "jpeg", "webp"],
    help=f"Maximum {MAX_UPLOAD_MB} MB.",
)

if uploaded:
    if uploaded.size > MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"Image is too large. Please upload an image under {MAX_UPLOAD_MB} MB.")
        st.stop()

    try:
        image = Image.open(uploaded).convert("RGB")
    except Exception:
        st.error("Could not read that image. Try a PNG or JPEG.")
        st.stop()

    left, right = st.columns([1.1, 1])
    with left:
        st.subheader("Uploaded image")
        st.image(image, use_container_width=True)
        st.caption(f"{image.width} × {image.height} pixels")

    client = make_client()
    if client is None:
        st.info(
            "To enable inspection, configure GEMINI_API_KEY in Streamlit Secrets "
            "or as an environment variable. See README.md."
        )
        st.stop()

    st.subheader("1 · Locate candidate solder joints")
    if st.button("Find solder joints", type="primary", use_container_width=False):
        with st.spinner("Gemini is locating visible solder-joint regions…"):
            try:
                detection = call_gemini(client, DETECT_PROMPT, image)
                st.session_state["detection"] = detection
                st.session_state["source_image_bytes"] = uploaded.getvalue()
                st.session_state["source_filename"] = uploaded.name
                st.session_state.pop("inspection", None)
            except Exception as exc:
                st.error(f"Detection request failed: {exc}")
                st.stop()

    detection = st.session_state.get("detection")
    if detection and st.session_state.get("source_filename") == uploaded.name:
        joints = detection.get("joints", [])
        with right:
            st.subheader("Candidate regions")
            if joints:
                st.image(draw_boxes(image, joints), use_container_width=True)
                st.caption("Cyan boxes are candidate regions proposed by Gemini; check them before inspection.")
            else:
                st.warning("Gemini did not return candidate joints. Use manual crop selection below.")

        st.write(detection.get("overall_assessment", ""))
        if detection.get("limitations"):
            st.caption("Detection limitations: " + "; ".join(map(str, detection["limitations"])))

        st.subheader("2 · Select the joint to inspect")
        selected_joint = None
        crop = None

        if joints:
            labels = []
            joint_map = {}
            for idx, joint in enumerate(joints):
                jid = joint.get("joint_id", idx + 1)
                desc = joint.get("description", "candidate joint")
                label = f"Joint {jid} — {desc[:75]}"
                labels.append(label)
                joint_map[label] = joint
            selected_label = st.selectbox("Choose a candidate box", labels)
            selected_joint = joint_map[selected_label]
            crop_box = box_to_pixels(selected_joint["box_2d"], image.width, image.height, padding=0.18)
            crop = image.crop(crop_box)
            st.image(crop, caption="Selected crop sent to Gemini for quality assessment", width=500)

        with st.expander("Can't find the correct joint? Select a crop manually"):
            st.caption("Adjust the crop rectangle using pixel coordinates. The crop preview below is what Gemini will inspect.")
            col1, col2, col3, col4 = st.columns(4)
            x = col1.number_input("Left (x)", min_value=0, max_value=max(0, image.width-1), value=0, step=max(1, image.width//20))
            y = col2.number_input("Top (y)", min_value=0, max_value=max(0, image.height-1), value=0, step=max(1, image.height//20))
            cw = col3.number_input("Width", min_value=1, max_value=image.width, value=max(1, image.width//3), step=max(1, image.width//20))
            ch = col4.number_input("Height", min_value=1, max_value=image.height, value=max(1, image.height//3), step=max(1, image.height//20))
            mx2, my2 = min(image.width, int(x+cw)), min(image.height, int(y+ch))
            manual_crop = image.crop((int(x), int(y), mx2, my2))
            st.image(manual_crop, caption="Manual crop preview", width=500)
            use_manual = st.checkbox("Inspect this manual crop instead", value=False)
            if use_manual:
                crop = manual_crop
                selected_joint = {"joint_id": "manual", "description": "Manual crop selected by user"}

        if crop is not None:
            if st.button("Inspect selected solder joint", type="primary"):
                with st.spinner("Gemini is assessing the selected solder region…"):
                    try:
                        inspection = call_gemini(client, INSPECT_PROMPT, crop)
                        st.session_state["inspection"] = inspection
                        st.session_state["inspection_joint_id"] = selected_joint.get("joint_id")
                    except Exception as exc:
                        st.error(f"Inspection request failed: {exc}")
                        st.stop()

        inspection = st.session_state.get("inspection")
        if inspection:
            st.divider()
            st.subheader(f"3 · Inspection result — Joint {st.session_state.get('inspection_joint_id', '?')}")
            recommendation = inspection.get("recommendation", "inspect_further")
            quality = inspection.get("quality", "uncertain")

            if recommendation == "accept":
                st.success("Recommendation: ACCEPT — no obvious visual defect identified")
            elif recommendation == "resolder":
                st.error("Recommendation: RESOLDER — a visible defect may require rework")
            elif recommendation == "finish_then_inspect":
                st.warning("Recommendation: FINISH SOLDERING, THEN INSPECT")
            else:
                st.warning("Recommendation: INSPECT FURTHER — evidence is insufficient")

            c1, c2, c3 = st.columns(3)
            c1.metric("Visual quality", quality.replace("_", " ").title())
            c2.metric("Joint status", inspection.get("joint_status", "unclear").replace("_", " ").title())
            c3.metric("Confidence", inspection.get("confidence", "low").title())

            st.markdown("**Description**")
            st.write(inspection.get("description", "No description returned."))
            st.markdown("**Reason for recommendation**")
            st.write(inspection.get("reason", "No reason returned."))

            defects = inspection.get("defects", [])
            st.markdown("**Possible visible defects**")
            if defects:
                for defect in defects:
                    st.write(f"- {defect}")
            else:
                st.write("No specific visible defect was reported.")

            limitations = inspection.get("limitations", [])
            if limitations:
                st.markdown("**Limitations**")
                for limitation in limitations:
                    st.write(f"- {limitation}")

            st.download_button(
                "Download inspection report (JSON)",
                data=json.dumps(inspection, indent=2, ensure_ascii=False),
                file_name="solder_inspection_report.json",
                mime="application/json",
            )
            st.caption(
                "Quality is based only on the supplied image crop. This does not verify electrical continuity, hidden bridges, or mechanical strength."
            )
else:
    st.markdown("### How it works")
    st.markdown(
        "1. Upload a PCB image.  \n"
        "2. Ask Gemini to locate candidate solder joints.  \n"
        "3. Select the correct box, or define a crop manually.  \n"
        "4. Inspect that crop and review the quality description and recommended action."
    )
