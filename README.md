# Solder Sight

Vision-assisted planning and closed-loop control for an automatic soldering machine.

1. **Plan** (browser): take a photo of the PCB, draw a reference box, enter its real size, let Gemini
   find the solder joints (or click them), export `job.json`. Positions are in mm from the
   **bottom-left** of the reference box.
2. **Run** (terminal): for each joint the machine moves in X/Y, lowers Z, triggers the solder pin,
   raises Z, photographs the joint and decides: **good**, **retry**, or **needs a human**.

> **Safety:** this software can move a hot tool. Always dry-run first, keep a physical emergency stop
> within reach, and verify limits and Z heights with the iron cold. See `docs/ARCHITECTURE.md`.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Download `job.json` from the app's Export section, then:

```bash
cp config/machine.example.yaml config/machine.yaml     # edit for your machine
python -m solder_sight.cli job.json -c config/machine.yaml                  # DRY RUN (default)
python -m solder_sight.cli job.json -c config/machine.yaml --image board.png  # dry run, no camera
python -m solder_sight.cli job.json -c config/machine.yaml --live             # real machine
```

Each run saves before/after crops and `results.csv` under `runs/`.

## Gemini API key (optional, for auto-detection)

Paste it in the sidebar, or copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`, or set
`GEMINI_API_KEY`. Never commit it. The cropped board image is sent to Google's API.
Prefer open source? See `solder_sight/detection.py`; add a backend there (YOLO, Molmo, Grounding DINO).

## Machine setup checklist

- [ ] `limits` match your real travel
- [ ] `z_safe` clears every component; `z_solder` verified with the iron cold
- [ ] `box_origin_x/y` = machine position of the reference box's bottom-left corner
- [ ] `on_cmd` / `off_cmd` / `sync_cmd` / `home_cmd` match your firmware (GRBL vs Marlin)
- [ ] Camera fixed, good even lighting (a ring light helps)
- [ ] Dry run output (the printed G-code) reviewed by a human

## Quality inspection

`HeuristicInspector` is a **baseline** (shiny-pixel coverage plus a before/after change check). Tune
`solder_ratio_min/max` on your own photos, then replace it with a trained classifier. The runner
saves labelled crops to help you build that dataset.

## Development

```bash
pip install -r requirements-dev.txt
ruff check . && pytest -q
```

## Layout

```
app.py                 planner UI (Streamlit)
solder_sight/          geometry, detection, job, machine, camera, inspection, runner, cli
config/                machine.example.yaml
docs/ARCHITECTURE.md   design and safety notes
tests/                 pytest suite (runs without hardware)
```

## License

MIT
