# SolderSight — PCB image crop and solder inspection

SolderSight is a Streamlit app for AI-assisted visual solder-joint review. The image workflow is intentionally simple: upload a PCB photo, draw a rectangle around the work area, preview the crop, and inspect it. No reference-point calibration step is required.

## Features

- Upload a PCB image and draw a rectangle directly on it to select a work area.
- Preview the selected crop and see its pixel coordinates and dimensions.
- Optionally enter the full PCB's real width and/or height in centimetres to estimate the crop's physical dimensions.
- Inspect the drawn crop with the configured Gemini vision model.
- Use the existing candidate-joint inspection workflow when you want AI-assisted candidate regions.
- Optional independent second review and JSON inspection report download.
- Primary model defaults to `gemini-3.8-flash`; on request failures, the app tries `gemini-3.5-flash` as fallback. Model IDs/access vary by API project; edit the model fields/constants if your key uses different IDs.

## Run locally

Python 3.11+ recommended.

```bash
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\\Scripts\\activate    # Windows
pip install -r requirements.txt
export GEMINI_API_KEY="YOUR_KEY"   # macOS/Linux
# PowerShell: $env:GEMINI_API_KEY="YOUR_KEY"
streamlit run app.py
```

Or configure `.streamlit/secrets.toml`:

```toml
GEMINI_API_KEY = "YOUR_KEY"
```

Never commit API keys or secrets files.

## Work-area crop workflow

1. Upload a clear PCB image.
2. Drag on the image to draw a rectangle around the region you want to work on.
3. Review the crop preview and pixel dimensions.
4. Optionally enter the full PCB width and/or height in centimetres. The app estimates crop width/height using the corresponding image dimension; use a straight-on image for the best estimate.
5. Click **Inspect this drawn crop** to run the visual review on the selected region.

If the drawing component fails to load, update dependencies with `pip install -r requirements.txt` and restart Streamlit. The app displays a fallback message and the existing manual crop controls remain available.

## Important limitations

- The crop is an image selection only; it does not move or control hardware.
- Centimetre dimensions are estimates based on the entered full-board dimensions and assume the image represents the board without significant perspective distortion.
- Visual analysis cannot prove electrical continuity, hidden defects, or mechanical strength. Validate on representative boards before relying on results.
- Uploaded images are sent to the configured third-party Gemini API for visual inspection. Do not upload confidential images unless your data policy permits it.
