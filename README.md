# MicroClinic — MVP

Minimal MicroClinic MVP for INNOSpark hackathon.

Purpose
- Guided, conservative triage for frontline health workers; generates evidence pack for clinician review.

Run (backend)
1. Open a terminal in `microclinic-mvp/backend`
2. Create and activate a venv

Windows:
```
python -m venv venv
venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

3. Open `microclinic-mvp/frontend/index.html` in a browser and point to `http://localhost:8000` for API.

What it includes
- FastAPI backend with simple rule-based triage, file-backed storage, and PDF evidence export.
- Single-page frontend (index.html) to submit cases and view results.

Notes
- This is a hackathon demo. All triage outputs are conservative suggestions — clinicians must confirm.
