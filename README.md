# SolderSight Playground

A Streamlit playground for AI-assisted visual review of PCB solder joints, with image upload and live-camera capture.

## Features

- White/light themed inspection workspace.
- Upload an image or capture one with `st.camera_input`.
- Automatic orientation normalization, resizing to at most 1400 px, and JPEG compression before analysis.
- One initial vision request assesses solder quality directly; optional second opinion is disabled by default.
- Structured report with quality, visible findings, confidence, image quality, limitations, and recommended action.
- Retry logic with exponential backoff and jitter for temporary service errors such as 503, 429, and 5xx.
- Optional fallback models after repeated overload errors.
- JSON report download.

## Setup

Python 3.11+ recommended.

```bash
python -m venv .venv
source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Configure your Gemini API key through an environment variable:

```bash
export GEMINI_API_KEY="YOUR_API_KEY"  # macOS/Linux
# PowerShell: $env:GEMINI_API_KEY="YOUR_API_KEY"
```

Or create `.streamlit/secrets.toml` locally:

```toml
GEMINI_API_KEY = "YOUR_API_KEY"
```

Never commit API keys or secrets to Git.

Run the app:

```bash
streamlit run app.py
```

## Model and fallback behavior

The default model is `gemini-2.5-flash`. Set `SOLDERSIGHT_MODEL` to change the default model, or use the sidebar field. When fallback is enabled, SolderSight tries `gemini-2.0-flash` after the selected model continues to return transient overload/rate-limit errors. The fallback model must be enabled for your API project and support image input. You can edit `FALLBACK_MODELS` in `app.py` to match models available to your account.

Transient errors are retried up to three times per model with exponential backoff and jitter. Retries cannot guarantee availability; if the provider remains unavailable, the app shows a friendly error and lets you retry without re-uploading the image.

## Deployment

Deploy to Streamlit Community Cloud by uploading `app.py`, `requirements.txt`, `README.md`, and `.gitignore`. Add `GEMINI_API_KEY` in the app's deployment secrets. Never include the key in the repository.

## Limitations and privacy

Images are sent to the configured external vision API. Do not upload confidential board images unless your data policy permits it. Visual analysis cannot confirm electrical continuity, hidden solder bridges, internal wetting, or mechanical strength. Validate with expert-labelled images before relying on results for production.
