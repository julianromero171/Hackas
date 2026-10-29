"""Pruebas del backend: CP-SAT garantiza 0 violaciones duras y la API responde."""
import pytest
from fastapi.testclient import TestClient

from backend.cpsat_solver import solve_cpsat
from backend.main import app, load_default
from backend.models import Rule, Weights

DEMO_RULES = [
    Rule(type="teacher_unavailable", teacherId="P01", days=[4], blocks=[4, 5], hard=True),
    Rule(type="teacher_unavailable", teacherId="P03", days=[0], blocks=[0, 1], hard=True),
    Rule(type="teacher_unavailable", teacherId="P07", days=[2], blocks=[3, 4, 5], hard=True),
    Rule(type="subject_avoid", subjectIds=["MAT", "FIS"], blocks=[4, 5]),
    Rule(type="subject_prefer_morning", subjectIds=["MAT"]),
]


@pytest.fixture(scope="module")
def solved():
    return solve_cpsat(load_default(), DEMO_RULES, Weights(), time_limit=20, workers=8)


def test_cpsat_feasible_zero_hard(solved):
    assert solved.status in ("OPTIMAL", "FEASIBLE")
    assert solved.metrics["hard"]["total"] == 0


def test_rules_respected(solved):
    data = load_default()
    B = data.jornada.bloquesPorDia
    carlos_courses = {c.id for c in data.cursos if any(i.docente == "P01" for i in c.plan)}
    for cid in carlos_courses:
        row = solved.horario[cid]
        assert row[4 * B + 4] != "MAT" and row[4 * B + 5] != "MAT"


def test_infeasible_input_detected():
    rule = Rule(type="teacher_unavailable", teacherId="P01", days=[0, 1, 2, 3], blocks=list(range(6)), hard=True)
    res = solve_cpsat(load_default(), [rule], Weights(), time_limit=5)
    assert res.status == "INFEASIBLE_INPUT"
    assert res.issues


def test_api_health_and_validate(solved):
    client = TestClient(app)
    assert client.get("/api/health").json()["ok"] is True
    r = client.post("/api/validate", json={"horario": solved.horario, "rules": [r.model_dump() for r in DEMO_RULES]})
    assert r.status_code == 200
    assert r.json()["hard"]["total"] == 0


def test_api_solve_endpoint():
    client = TestClient(app)
    r = client.post("/api/solve", json={"timeLimit": 8})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("OPTIMAL", "FEASIBLE")
    assert len(body["horario"]) == 6
