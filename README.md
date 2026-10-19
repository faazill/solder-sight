# SolderSight — Gemini-powered solder inspection web app

A beginner-friendly Streamlit app that lets a user upload a PCB image, ask Gemini to locate candidate solder-joint regions, select one region, and request a focused visual assessment. It reports visible evidence, potential defects, uncertainty, and a recommended next step.

## Features

- Upload PNG/JPG/JPEG/WEBP images.
- Ask Gemini to locate candidate solder-joint boxes.
- Select a candidate box or choose a manual crop using pixel coordinates.
- Inspect only the selected crop for visible solder quality.
- Results include `accept`, `resolder`, `inspect_further`, or `finish_then_inspect`.
- Download the result as JSON.
- API key is read server-side from Streamlit Secrets or an environment variable.

## 1. Get a Gemini API key

Create an API key in Google AI Studio: https://aistudio.google.com/apikey

Do not commit the key to GitHub or put it in client-side code.

## 2. Run locally

Python 3.11 or 3.12 recommended.

```bash
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate        # Windows

pip install -r requirements.txt
```

Set the key as an environment variable:

```bash
export GEMINI_API_KEY="YOUR_KEY_HERE"   # macOS/Linux
# PowerShell:
# $env:GEMINI_API_KEY="YOUR_KEY_HERE"
```

Then run:

```bash
streamlit run app.py
```

The app should open at http://localhost:8501.

## 3. Publish for free with Streamlit Community Cloud

1. Create a GitHub repository, for example `soldersight`.
2. Upload `app.py`, `requirements.txt`, `README.md`, and `.gitignore`.
3. Do **not** upload an API key or a real `.streamlit/secrets.toml`.
4. Open https://share.streamlit.io and sign in with GitHub.
5. Choose **Create app**, select your repository and branch, and set the entrypoint to `app.py`.
6. In **Advanced settings / Secrets**, add:

```toml
GEMINI_API_KEY = "YOUR_REAL_GEMINI_API_KEY"
```

7. Deploy. Streamlit gives the app a public URL ending in `streamlit.app`.

Official docs:
- Deploy: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app
- Secrets: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- Gemini models: https://ai.google.dev/gemini-api/docs/models

## Model configuration

The default model is `gemini-3.8-flash`. If this model is not enabled for your API project, choose an available image-capable model in the sidebar or change `DEFAULT_MODEL` in `app.py`.

## Safety and limitations

- This is a prototype and has not been validated as an industrial quality-control system.
- General-purpose vision models can miss or hallucinate defects. Test on representative, real, completed joints with expert labels.
- A visual image cannot establish electrical continuity, hidden defects, or mechanical strength.
- If the iron is touching the joint or solder is molten, the correct workflow is to finish soldering and inspect again.
- Anyone with access to a public app can potentially consume your API quota. Add authentication or rate limiting before wider public use.
- Images are sent to the Gemini API for analysis. Do not upload sensitive or proprietary images unless your organization's data policies allow it.
