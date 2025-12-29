# Arsha’s Lost & Found (FastAPI)

A Lost & Found web app that lets users submit Lost/Found reports and automatically suggests matches.
Users can claim matches, founders can approve/reject, and the system supports settlement + disputes.

## One-click try

### ✅ GitHub Codespaces
Open the repo → **Code** → **Codespaces** → **Create codespace**.  
(If `.devcontainer/` exists, it auto-installs dependencies.)

Then run:
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
