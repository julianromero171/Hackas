"""
API FastAPI de GnoSoft Timetable AI.

  uvicorn backend.main:app --reload --port 8000     →  http://localhost:8000  (UI + API)
  Documentación interactiva: http://localhost:8000/docs
"""
from __future__ import annotations

from pathlib import Path

import ortools
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .cpsat_solver import solve_cpsat
from .fitness import evaluate
from .models import SchoolData, SolveRequest, SolveResponse, ValidateRequest
from .problem import build_problem

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "data" / "school.json"

app = FastAPI(
    title="GnoSoft Timetable AI",
    version="1.0.0",
    description="Generación inteligente de horarios escolares: CSP + Kempe + Simulated Annealing (cliente) y Google OR-Tools CP-SAT (servidor).",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def load_default() -> SchoolData:
    return SchoolData.model_validate_json(DEFAULT_DATA.read_text(encoding="utf-8"))


@app.get("/api/health", tags=["sistema"])
def health():
    return {"ok": True, "engine": "Google OR-Tools CP-SAT", "ortools": ortools.__version__}


@app.get("/api/sample", response_model=SchoolData, tags=["datos"])
def sample():
    """Datos de ejemplo: 6 cursos (6°A–8°B), 13 docentes, 10 espacios."""
    return load_default()


@app.post("/api/solve", response_model=SolveResponse, tags=["optimización"])
def solve(req: SolveRequest):
    """Recibe datos + reglas + pesos en JSON y retorna la matriz del horario optimizado y sus métricas."""
    data = req.data or load_default()
    return solve_cpsat(data, req.rules, req.weights, time_limit=req.timeLimit, workers=req.workers)


@app.post("/api/validate", tags=["optimización"])
def validate(req: ValidateRequest):
    """Evalúa (fitness) un horario existente: violaciones duras y métricas blandas."""
    data = req.data or load_default()
    pb = build_problem(data, req.rules)
    return {"issues": pb.issues, **evaluate(pb, req.horario)}


# ---- Frontend estático (solo carpetas públicas) ----
for folder in ("css", "js", "data"):
    app.mount(f"/{folder}", StaticFiles(directory=ROOT / folder), name=folder)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "index.html")
