"""
Motor exacto con Google OR-Tools CP-SAT.

Variables:  x[k,t] ∈ {0,1}  ⇔  el ítem de plan k = (curso c, asignatura m, docente p) se dicta en el slot t=(d,b).
(Equivale a X[c,m,p,a,d,b]; el aula a se asigna por emparejamiento de capacidad por slot, garantizado
factible por las restricciones de Hall sobre umbrales de capacidad.)

Duras:
  Σ_t x[k,t] = h_k                                  (horas del plan)
  Σ_{k∈c} x[k,t] ≤ 1                                (0 cruces por curso)
  Σ_{k∈p} x[k,t] ≤ 1 ; x[k,t]=0 si p no disponible  (0 cruces + disponibilidad docente)
  x[k,t]=0 si (m,t) prohibido                       (reglas duras del copiloto)
  ∀ tipo, ∀ q: Σ_{k: tipo, tamaño≥q} x[k,t] ≤ #aulas(tipo, cap≥q)   (aulas: tipo + capacidad, 0 colisiones)
Blandas (minimizar):
  w_h·huecos + w_f·fatiga + w_m·franjas + w_e·equidad
"""
from __future__ import annotations

import math
from collections import defaultdict

from ortools.sat.python import cp_model

from .fitness import evaluate
from .models import Rule, SchoolData, SolveResponse, Weights
from .problem import build_problem

SCALE = 10  # los pesos (0..10, float) se escalan a enteros


def solve_cpsat(data: SchoolData, rules: list[Rule], weights: Weights,
                time_limit: float = 10.0, workers: int = 8, seed: int = 0) -> SolveResponse:
    pb = build_problem(data, rules)
    if pb.blocking:
        return SolveResponse(status="INFEASIBLE_INPUT", issues=pb.issues)

    D, B, S = pb.D, pb.B, pb.S
    m = cp_model.CpModel()
    x: dict[tuple[int, int], cp_model.IntVar] = {}
    by_course, by_teacher, by_type = defaultdict(list), defaultdict(list), defaultdict(list)
    for k, it in enumerate(pb.items):
        by_course[it.c].append(k)
        by_teacher[it.p].append(k)
        by_type[it.type].append(k)
        for t in range(S):
            if (it.p, t) in pb.unavailable or (it.s, t) in pb.forbidden:
                continue
            x[k, t] = m.NewBoolVar(f"x_{k}_{t}")

    def at(ks, t):
        return [x[k, t] for k in ks if (k, t) in x]

    # --- Duras ---
    for k, it in enumerate(pb.items):
        m.Add(sum(x[k, t] for t in range(S) if (k, t) in x) == it.hours)
    for ks in by_course.values():
        for t in range(S):
            vs = at(ks, t)
            if len(vs) > 1:
                m.AddAtMostOne(vs)
    for ks in by_teacher.values():
        for t in range(S):
            vs = at(ks, t)
            if len(vs) > 1:
                m.AddAtMostOne(vs)
    for ty, ks in by_type.items():
        caps = pb.type_caps.get(ty, [])
        sizes = sorted({pb.items[k].size for k in ks})
        for t in range(S):
            for q in sizes:
                vs = [x[k, t] for k in ks if pb.items[k].size >= q and (k, t) in x]
                supply = sum(1 for cap in caps if cap >= q)
                if len(vs) > supply:
                    m.Add(sum(vs) <= supply)

    obj = []
    wg, wf, wm, we = (int(round(getattr(weights, n) * SCALE)) for n in ("gaps", "fatigue", "morning", "equity"))

    # --- Horas huecas docentes ---
    if wg > 0:
        for p, ks in by_teacher.items():
            for d in range(D):
                busy = [at(ks, d * B + b) for b in range(B)]
                before = [None] * B
                after = [None] * B
                for b in range(1, B):
                    v = m.NewBoolVar("")
                    for e in busy[b - 1]:
                        m.Add(v >= e)
                    if before[b - 1] is not None:
                        m.Add(v >= before[b - 1])
                    before[b] = v
                for b in range(B - 2, -1, -1):
                    v = m.NewBoolVar("")
                    for e in busy[b + 1]:
                        m.Add(v >= e)
                    if after[b + 1] is not None:
                        m.Add(v >= after[b + 1])
                    after[b] = v
                for b in range(1, B - 1):
                    g = m.NewBoolVar("")
                    m.Add(g >= before[b] + after[b] - 1 - sum(busy[b]))
                    obj.append(wg * g)

    # --- Fatiga cognitiva y equidad ---
    for c, ks in by_course.items():
        heavy = [k for k in ks if pb.items[k].heavy]
        for d in range(D):
            H = [sum(at(heavy, d * B + b)) for b in range(B)]
            if wf > 0 and heavy:
                for b in range(B):
                    if b == B - 1:
                        obj.append(wf * H[b])
                    elif b not in pb.break_after:
                        f = m.NewBoolVar("")
                        m.Add(f >= H[b] + H[b + 1] - 1)
                        obj.append(wf * f)
            if we > 0:
                for k in ks:
                    allowed = math.ceil(pb.items[k].hours / D)
                    day = [x[k, d * B + b] for b in range(B) if (k, d * B + b) in x]
                    if len(day) > allowed:
                        e = m.NewIntVar(0, B, "")
                        m.Add(e >= sum(day) - allowed)
                        obj.append(we * e)
                if heavy:
                    hd = m.NewIntVar(0, B, "")
                    m.Add(hd >= sum(H) - pb.heavy_cap[c])
                    obj.append(we * hd)

    # --- Franjas (reglas blandas del copiloto) ---
    if wm > 0:
        for (k, t), v in x.items():
            pen = pb.soft_slot.get((pb.items[k].s, t), 0)
            if pen:
                obj.append(int(round(wm * pen)) * v)

    if obj:
        m.Minimize(sum(obj))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_workers = int(workers)
    solver.parameters.random_seed = int(seed)
    status = solver.Solve(m)
    name = solver.StatusName(status)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return SolveResponse(status=name, wallTimeMs=solver.WallTime() * 1000, branches=solver.NumBranches(),
                             issues=["El modelo no tiene solución con las restricciones actuales."])

    horario: dict[str, list] = {c.id: [None] * S for c in data.cursos}
    for (k, t), v in x.items():
        if solver.Value(v):
            it = pb.items[k]
            horario[it.course_id][t] = it.subject_id

    return SolveResponse(
        status=name,
        wallTimeMs=solver.WallTime() * 1000,
        objective=solver.ObjectiveValue() / SCALE if obj else 0.0,
        branches=solver.NumBranches(),
        horario=horario,
        metrics=evaluate(pb, horario),
    )
