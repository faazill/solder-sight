# SolderSight — professional starter app

SolderSight is a Streamlit web app for AI-assisted visual review of PCB solder joints. The main interface is branded as SolderSight; provider/API information is available in the Privacy & system information section.

## Improvements in this version
- Cleaner industrial-style interface and guided 3-step workflow.
- Candidate regions with visible boxes, selected-crop preview, and manual crop fallback.
- Image orientation normalization and resizing to a practical maximum resolution.
- Structured inspection output: status, visible findings, severity, explanation, confidence, image quality, limitations, and recommended action.
- Optional second independent review. If reviews disagree, the app downgrades an unconditional acceptance to manual inspection.
- Defensive JSON parsing and user-readable errors.
- JSON report download.
- Server-side API key configuration; never store keys in source code or GitHub.

## Setup locally
Python 3.11+ recommended.

```bash
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

Set your key:
```bash
export GEMINI_API_KEY="YOUR_KEY"   # macOS/Linux
# PowerShell: $env:GEMINI_API_KEY="YOUR_KEY"
streamlit run app.py
```

Or create `.streamlit/secrets.toml` locally:
```toml
GEMINI_API_KEY = "YOUR_KEY"
```
Never commit that file.

## Deploy to Streamlit Community Cloud
1. Create a GitHub repository.
2. Upload `app.py`, `requirements.txt`, `README.md`, and `.gitignore`.
3. Do not upload your API key or secrets file.
4. Sign in at https://share.streamlit.io and create an app from the repository.
5. Choose `app.py` as the entrypoint.
6. Add the secret in the deployment settings:
```toml
GEMINI_API_KEY = "YOUR_REAL_KEY"
```
7. Deploy and use the public URL Streamlit provides.

Docs:
- Deploy: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app
- Secrets: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- Current model list: https://ai.google.dev/gemini-api/docs/models
- Image understanding: https://ai.google.dev/gemini-api/docs/image-understanding

## Model
Default is `gemini-3.8-flash`, listed as a stable image-capable model in Google's model documentation as checked on 2026-10-19. If unavailable for your account, change it in the sidebar to an image-capable model enabled for your API project.

## Responsible use
- A more polished UI or a second model review does not prove higher accuracy. Validate using representative real images and expert-labelled ground truth.
- The app must not be treated as a certified industrial inspection system.
- A photo cannot confirm electrical continuity, hidden solder bridges, internal wetting, or mechanical strength.
- Public deployment can incur API usage charges. Add authentication, quotas/rate limiting, and monitoring before sharing broadly.
- Uploaded images are sent to the configured third-party vision API. Do not upload proprietary boards unless your data policy permits it.
- The interface is branded as SolderSight without provider branding, but the privacy disclosure states that an external vision API is used.
