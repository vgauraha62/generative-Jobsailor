# JobSailor — Frontend Demo (GitHub Pages)

Static proof-of-work for `https://github.com/GoliathReaper/JobSailor`.

- **Live demo:** `https://<user>.github.io/JobSailor/` (via `docs/` on `main`)
- **Source:** `web/static/` + `web/static/assets/app.css` — vanilla HTML/CSS/JS, Chart.js CDN, no build step.

## What this is
Pixel-identical clone of the FastAPI dashboard (`dashboard`, `reports`, `chat/rag`, `credentials`, `settings`, `help`, `landing`) but running without Python/Gemini/Selenium. All `/api/*` calls are intercepted by `assets/demo.js` with sanitized mock data — runs/uploads are disabled (toast: "Demo mode").

## Deploy
1. Push `docs/` to `main`. Repo Settings → Pages → Source: `Deploy from a branch` → `main` / `docs`.
2. Or `git subtree push --prefix docs origin gh-pages` if using `gh-pages` branch.
3. Custom domain via `docs/CNAME`.

## Local preview
```bash
python -m http.server --directory docs 8000
# http://localhost:8000
```

## Notes
- No secrets in this folder (`.env`, `candidate_profile.json`, `cookies.txt`, `reports/` excluded).
- Replace `demo.js` MOCK data with a snapshot from `curl http://localhost:8000/api/status` for fresher demo numbers.
