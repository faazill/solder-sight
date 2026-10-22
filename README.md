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

The default model ID is `gemini-flash-latest`, but model access differs by API key and project. Click **Discover available models** in the sidebar to query the Models API and choose a model returned for your key. The app filters for Gemini-family models supporting `generateContent` and excludes clearly non-vision tasks; confirm that the selected model supports image input in your Google AI Studio project. Set `SOLDERSIGHT_MODEL` or use the manual model ID field to override the default. When fallback is enabled, the app prefers discovered models and otherwise tries configurable candidates from `FALLBACK_MODELS`.

Transient errors are retried up to three times per model with exponential backoff and jitter. A missing/unsupported model can trigger a fallback attempt, but invalid keys and permission errors are not hidden. Model discovery depends on the API key having permission to list models. Retries cannot guarantee availability; if the provider remains unavailable, the app shows a friendly error and lets you retry without re-uploading the image.

## Deployment

Deploy to Streamlit Community Cloud by uploading `app.py`, `requirements.txt`, `README.md`, and `.gitignore`. Add `GEMINI_API_KEY` in the app's deployment secrets. Never include the key in the repository.

## Limitations and privacy

Images are sent to the configured external vision API. Do not upload confidential board images unless your data policy permits it. Visual analysis cannot confirm electrical continuity, hidden solder bridges, internal wetting, or mechanical strength. Validate with expert-labelled images before relying on results for production.
