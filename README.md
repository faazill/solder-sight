# SolderSight Playground — PCB solder quality review

SolderSight is a Streamlit playground for AI-assisted visual review of PCB solder joints. The interface is inspired by modern robotics/AI playgrounds: a focused workspace, input canvas, analysis controls, result panel, and recent-run list.

## Features

- **Upload image** or **Live camera** input.
- Camera capture through Streamlit's `st.camera_input`; take a photo, preview it, then press **Analyze Solder Quality**.
- Local image normalization and resizing to a maximum longest dimension of 1400 px, followed by JPEG compression before the image is sent to the vision API.
- One initial vision request directly assesses the visible solder quality; there is no separate joint-location request.
- Optional independent second review is available in the sidebar but disabled by default to keep the standard workflow faster.
- Results include visible quality, joint status, defects and evidence, confidence, image-quality notes, and a recommended next action.
- JSON inspection report download and recent-run history for the current session.
- Responsive dark playground-style interface with privacy and system information.

## Run locally

Python 3.11+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

Configure your Gemini API key as an environment variable:

```bash
export GEMINI_API_KEY="YOUR_KEY"   # macOS/Linux
# PowerShell: $env:GEMINI_API_KEY="YOUR_KEY"
streamlit run app.py
```

Alternatively, create `.streamlit/secrets.toml` locally:

```toml
GEMINI_API_KEY = "YOUR_KEY"
```

Never commit your API key or secrets file.

## Deploy to Streamlit Community Cloud

1. Push `app.py`, `requirements.txt`, `README.md`, and optionally `.gitignore` to a GitHub repository.
2. Create an app at https://share.streamlit.io and select `app.py` as the entrypoint.
3. Add `GEMINI_API_KEY` in the app's deployment secrets.

## Privacy and responsible use

- Images are sent to the configured third-party vision API. Do not upload confidential board images unless your data policy permits it.
- This is visual decision support, not a certified industrial inspection system. Visual analysis cannot prove electrical continuity, hidden defects, internal wetting, or mechanical strength.
- Validate with representative, expert-labelled images before relying on results operationally.
- Public deployment may incur API charges. Add authentication, quotas/rate limiting, and monitoring before sharing broadly.
