# JobSailor — fresh setup

Selenium + Gemini bot for Naukri.com job applications, with a FastAPI control panel.

## System deps

Firefox, geckodriver (on `PATH`), tesseract binary (resume OCR).

## Install

```bash
python -m venv venv
venv/bin/pip install -r requirements.txt   # add -dev for pytest
cp config.example.json config.json          # edit slugs, profile path, limits
cp .env.example .env                        # fill in below
```

## Configure

- `GEMINI_API_KEY` — required (Google AI Studio).
- `GEMINI_MODEL` — default `gemini-3.5-flash-lite`.
- `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` — optional; spent only when Gemini
  quota exhausts mid-run (spillover). Key absence = skip on quota.
- `WEB_UI_USER` plus `WEB_UI_PASSWORD_HASH` / `WEB_UI_SECRET_KEY` from:
  `venv/bin/python scripts/generate_password_hash.py`

## Run

```bash
venv/bin/uvicorn web.server:app --host 127.0.0.1 --port 8000
```

Log in to Naukri once in Firefox using the configured profile
(`browser.profile_path`), then start runs from the dashboard. Per-user data
(`data/`, `reports/`, resumes) is created at runtime and never committed.
