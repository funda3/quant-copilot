# Quant Copilot

ZAR quant workbench - FastAPI backend + Streamlit UI.

---

## Local startup (two terminals)

### Terminal 1 — Backend

```powershell
cd C:\quant-copilot\backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001
```

Health check: `http://127.0.0.1:8001/healthz`
Interactive docs: `http://127.0.0.1:8001/docs`

### Terminal 2 — Streamlit app

```powershell
cd C:\quant-copilot\streamlit-app
.venv\Scripts\python.exe -m streamlit run app.py
```

Opens at `http://localhost:8501`.

---

## Canonical port

`8001` is the canonical local backend port for this repo. The Streamlit app
(`streamlit-app/app.py`) hard-targets `http://127.0.0.1:8001`. Do not start
the backend on 8000 and expect the UI to work without changing that constant.

---

## Virtual environments

Each sub-repo maintains its own local venv. Install steps are in each sub-repo's `README.md`.

| Repo | venv path |
|---|---|
| `backend/` | `backend/.venv` |
| `streamlit-app/` | `streamlit-app/.venv` |
| `quant-core/` | install into backend venv via `-e ../quant-core` |
