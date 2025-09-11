# CAMCO — Carbon-Aware Multi-Cloud Orchestrator (MVP)

A tiny demo that schedules batch jobs across cloud regions to **minimize carbon emissions (CO₂e)** while respecting **latency** and **cost** constraints. It produces an **audit-ready PDF** report and supports **manual overrides**.

---

## Why this is relevant
- Treats **carbon as a first-class SLO** (Green SLA) next to cost & latency.
- **Explainable** output with a signed-style decision report.
- Lines up with Accenture focus areas: **Cloud, Sustainability, Trust**.

---

## Quickstart

### Backend (FastAPI + SQLite)
```bash
# from project root
python -m venv .venv
.\.venv\Scripts\Activate.ps1     # (Windows PowerShell)
pip install -r requirements.txt  # or: pip install fastapi uvicorn reportlab pydantic
uvicorn app.main:app --reload --port 8000 --app-dir backend

## Demo Screenshots

### Frontend
![Demo Screenshot](FrontendCamco.png)

### Backend
![Backend Screenshot](BackendCamco.png)




