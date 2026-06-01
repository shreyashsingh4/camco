from fastapi.responses import FileResponse
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import os, time
from typing import Optional
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from datetime import datetime

app = FastAPI(title="CAMCO")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "camco.db")
API_KEY = os.getenv("API_KEY", "devkey")

def get_db():
    return sqlite3.connect(DB_PATH)

def require_api_key(x_api_key: str | None):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

class SignalIn(BaseModel):
    region: str
    provider: str
    carbon_gco2_per_kwh: float
    usd_per_cpu_hour: float
    usd_per_gpu_hour: float
    latency_to_data_ms: int

class JobIn(BaseModel):
    name: str
    cpu_hours: float
    gpu_hours: float
    deadline_minutes: int
    latency_budget_ms: int
    data_region: str
    cost_cap_usd: float
    carbon_weight: float = 0.7
    cost_weight: float = 0.3

with get_db() as conn:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS regions(
        region TEXT PRIMARY KEY,
        provider TEXT,
        carbon REAL,
        cpu_price REAL,
        gpu_price REAL,
        latency_ms INT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS jobs(
        id TEXT PRIMARY KEY,
        name TEXT,
        cpu_hours REAL,
        gpu_hours REAL,
        deadline_minutes INT,
        latency_budget_ms INT,
        data_region TEXT,
        cost_cap_usd REAL,
        carbon_weight REAL,
        cost_weight REAL,
        status TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS plans(
        job_id TEXT,
        region TEXT,
        co2e REAL,
        cost REAL,
        feasible INT,
        score REAL,
        chosen INT DEFAULT 0
    )
    """)

def calc_plan(job: JobIn, r_row: tuple):
    region, _, carbon, cpu_p, gpu_p, latency = r_row
    kwh = job.cpu_hours * 0.5 + job.gpu_hours * 3.0
    co2e_kg = (kwh * carbon) / 1000.0
    cost_usd = job.cpu_hours * cpu_p + job.gpu_hours * gpu_p
    feasible = int((latency <= job.latency_budget_ms) and (cost_usd <= job.cost_cap_usd))
    norm_cost = cost_usd / max(1.0, job.cost_cap_usd)
    norm_co2 = co2e_kg / max(1.0, kwh)
    score = job.carbon_weight * norm_co2 + job.cost_weight * norm_cost
    return region, co2e_kg, cost_usd, feasible, score

@app.get("/health")
def health():
    return {"ok": True, "service": "camco", "stage": "jobs-ready"}

@app.post("/api/signals")
def upsert_signal(signal: SignalIn, x_api_key: str | None = Header(default=None)):
    require_api_key(x_api_key)
    with get_db() as conn:
        conn.execute(
            "REPLACE INTO regions(region, provider, carbon, cpu_price, gpu_price, latency_ms) VALUES(?,?,?,?,?,?)",
            (
                signal.region,
                signal.provider,
                signal.carbon_gco2_per_kwh,
                signal.usd_per_cpu_hour,
                signal.usd_per_gpu_hour,
                signal.latency_to_data_ms,
            ),
        )
    return {"ok": True, "region": signal.region}

@app.get("/api/regions")
def list_regions(x_api_key: str | None = Header(default=None)):
    require_api_key(x_api_key)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT region, provider, carbon, cpu_price, gpu_price, latency_ms FROM regions"
        ).fetchall()
    return [
        {
            "region": r[0],
            "provider": r[1],
            "carbon_gco2_per_kwh": r[2],
            "usd_per_cpu_hour": r[3],
            "usd_per_gpu_hour": r[4],
            "latency_to_data_ms": r[5],
        }
        for r in rows
    ]

@app.get("/api/jobs", tags=["dev"])
def list_jobs(x_api_key: str | None = Header(default=None)):
    require_api_key(x_api_key)
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, name, cpu_hours, gpu_hours, deadline_minutes,
                   latency_budget_ms, data_region, cost_cap_usd,
                   carbon_weight, cost_weight, status
            FROM jobs
            ORDER BY id DESC
        """).fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "cpu_hours": r[2],
            "gpu_hours": r[3],
            "deadline_minutes": r[4],
            "latency_budget_ms": r[5],
            "data_region": r[6],
            "cost_cap_usd": r[7],
            "carbon_weight": r[8],
            "cost_weight": r[9],
            "status": r[10],
        }
        for r in rows
    ]

@app.post("/api/jobs")
def submit_job(job: JobIn, x_api_key: str | None = Header(default=None)):
    require_api_key(x_api_key)
    jid = f"job_{int(time.time() * 1000)}"
    with get_db() as conn:
        conn.execute("""
            INSERT INTO jobs(id, name, cpu_hours, gpu_hours, deadline_minutes,
                             latency_budget_ms, data_region, cost_cap_usd,
                             carbon_weight, cost_weight, status)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, (jid, job.name, job.cpu_hours, job.gpu_hours, job.deadline_minutes,
              job.latency_budget_ms, job.data_region, job.cost_cap_usd,
              job.carbon_weight, job.cost_weight, "queued"))

        regions = conn.execute(
            "SELECT region, provider, carbon, cpu_price, gpu_price, latency_ms FROM regions"
        ).fetchall()

        if not regions:
            raise HTTPException(status_code=400, detail="No regions configured. Seed /api/signals first.")

        best = None

        for r in regions:
            region, co2e, cost, feasible, score = calc_plan(job, r)
            conn.execute("""
                INSERT INTO plans(job_id, region, co2e, cost, feasible, score, chosen)
                VALUES(?,?,?,?,?,?,0)
            """, (jid, region, co2e, cost, feasible, score))

            if feasible and (best is None or score < best[0]):
                best = (score, region)

        if best:
            conn.execute("UPDATE jobs SET status='planned' WHERE id=?", (jid,))
            conn.execute("UPDATE plans SET chosen=1 WHERE job_id=? AND region=?", (jid, best[1]))
        else:
            conn.execute("UPDATE jobs SET status='infeasible' WHERE id=?", (jid,))

    return {"job_id": jid}

@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, x_api_key: str | None = Header(default=None)):
    require_api_key(x_api_key)
    with get_db() as conn:
        j = conn.execute("SELECT id, name, status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not j:
            raise HTTPException(status_code=404, detail="Job not found")

        plans = conn.execute("""
            SELECT region, co2e, cost, feasible, score, chosen
            FROM plans WHERE job_id=?
            ORDER BY score ASC
        """, (job_id,)).fetchall()

    return {
        "job": {"id": j[0], "name": j[1], "status": j[2]},
        "plans": [
            {
                "region": p[0],
                "co2e_kg": p[1],
                "cost_usd": p[2],
                "feasible": bool(p[3]),
                "score": p[4],
                "chosen": bool(p[5]),
            } for p in plans
        ]
    }

@app.post("/api/override/{job_id}")
def override_plan(
    job_id: str,
    region: str,
    rationale: Optional[str] = "operator-override",
    x_api_key: str | None = Header(default=None)
):
    require_api_key(x_api_key)
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM plans WHERE job_id=? AND region=? AND feasible=1",
            (job_id, region)
        ).fetchone()

        if not row:
            raise HTTPException(status_code=400, detail="Region not feasible or not found for this job")

        conn.execute("UPDATE plans SET chosen=0 WHERE job_id=?", (job_id,))
        conn.execute("UPDATE plans SET chosen=1 WHERE job_id=? AND region=?", (job_id, region))
        conn.execute("UPDATE jobs SET status='planned' WHERE id=?", (job_id,))

    return {"ok": True, "job_id": job_id, "region": region, "rationale": rationale}

@app.get("/api/reports/{job_id}")
def generate_report(job_id: str, x_api_key: str | None = Header(default=None)):
    require_api_key(x_api_key)
    with get_db() as conn:
        job = conn.execute("SELECT id, name, status FROM jobs WHERE id=?", (job_id,)).fetchone()

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        plan = conn.execute("""
            SELECT region, co2e, cost, feasible, score, chosen
            FROM plans WHERE job_id=?
            ORDER BY chosen DESC, score ASC
            LIMIT 1
        """, (job_id,)).fetchone()

        if not plan:
            raise HTTPException(status_code=400, detail="No plans found for this job")

    pdf_path = os.path.join(os.path.dirname(__file__), "..", f"reports_{job_id}.pdf")

    c = canvas.Canvas(pdf_path, pagesize=A4)
    c.setTitle("CAMCO Decision Report")

    y = 800
    for line in [
        "CAMCO Decision Report",
        f"Generated (UTC): {datetime.utcnow().isoformat()}Z",
        f"Job ID: {job[0]}",
        f"Job Name: {job[1]}",
        f"Status: {job[2]}",
        "----",
        f"Chosen Region: {plan[0]}",
        f"Estimated CO2e (kg): {round(plan[1], 3)}",
        f"Estimated Cost (USD): {round(plan[2], 3)}",
        f"Feasible: {bool(plan[3])}",
        f"Score: {round(plan[4], 6)}",
    ]:
        c.drawString(72, y, line)
        y -= 20

    c.showPage()
    c.save()

    return {"pdf": pdf_path}

@app.get("/api/reports/{job_id}/file")
def download_report_file(job_id: str, x_api_key: str | None = Header(default=None)):
    require_api_key(x_api_key)

    pdf_path = os.path.join(os.path.dirname(__file__), "..", f"reports_{job_id}.pdf")

    if not os.path.exists(pdf_path):
        generate_report(job_id, x_api_key)

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"reports_{job_id}.pdf"
    )