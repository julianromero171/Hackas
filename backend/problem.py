"""Construcción del problema indexado (equivalente a js/engine/model.js)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .models import Rule, SchoolData

AVOID_PENALTY = 4


@dataclass
class Item:
    """Bloque de plan: (curso, asignatura, docente) con h horas semanales."""
    c: int
    s: int
    p: int
    hours: int
    heavy: bool
    type: str
    size: int
    course_id: str
    subject_id: str


@dataclass
class Problem:
    data: SchoolData
    D: int
    B: int
    S: int
    items: list[Item]
    unavailable: set[tuple[int, int]] = field(default_factory=set)   # (p, t)
    forbidden: set[tuple[int, int]] = field(default_factory=set)     # (s, t)
    soft_slot: dict[tuple[int, int], float] = field(default_factory=dict)  # (s, t) -> penalización
    break_after: set[int] = field(default_factory=set)
    type_caps: dict[str, list[int]] = field(default_factory=dict)
    heavy_cap: list[int] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return bool(self.issues)


def build_problem(data: SchoolData, rules: list[Rule]) -> Problem:
    J = data.jornada
    D, B = len(J.dias), J.bloquesPorDia
    S = D * B
    t_idx = {t.id: i for i, t in enumerate(data.docentes)}
    s_idx = {s.id: i for i, s in enumerate(data.asignaturas)}

    items: list[Item] = []
    heavy_cap: list[int] = []
    issues: list[str] = []
    type_caps: dict[str, list[int]] = {}
    for a in data.aulas:
        type_caps.setdefault(a.tipo, []).append(a.capacidad)

    for ci, c in enumerate(data.cursos):
        heavy_hours = 0
        total = 0
        for it in c.plan:
            sub = data.asignaturas[s_idx[it.asignatura]]
            heavy = sub.cargaCognitiva == "alta"
            heavy_hours += it.horas if heavy else 0
            total += it.horas
            if not any(cap >= c.estudiantes for cap in type_caps.get(sub.tipoEspacio, [])):
                issues.append(f"No existe espacio '{sub.tipoEspacio}' con capacidad para {c.nombre}.")
            items.append(Item(ci, s_idx[it.asignatura], t_idx[it.docente], it.horas, heavy,
                              sub.tipoEspacio, c.estudiantes, c.id, sub.id))
        heavy_cap.append(max(1, math.ceil(heavy_hours / D)))
        if total > S:
            issues.append(f"{c.nombre}: plan de {total} h excede {S} bloques.")

    pb = Problem(data=data, D=D, B=B, S=S, items=items, type_caps=type_caps, heavy_cap=heavy_cap, issues=issues)
    pb.break_after = {r.despuesDeBloque - 1 for r in J.recreos if 0 <= r.despuesDeBloque - 1 < B - 1}

    for pi, t in enumerate(data.docentes):
        for nd in t.noDisponible:
            if nd.dia not in J.dias:
                continue
            d = J.dias.index(nd.dia)
            for b1 in nd.bloques:
                if 1 <= b1 <= B:
                    pb.unavailable.add((pi, d * B + b1 - 1))

    all_days = list(range(D))
    for r in rules:
        if not r.enabled:
            continue
        r_days = r.days or all_days
        if r.type == "teacher_unavailable" and r.teacherId in t_idx:
            pi = t_idx[r.teacherId]
            cells = r.slots or [[d, b] for d in r_days for b in r.blocks]
            for d, b in cells:
                if 0 <= d < D and 0 <= b < B:
                    pb.unavailable.add((pi, d * B + b))
        elif r.type == "subject_avoid":
            for sid in r.subjectIds:
                if sid not in s_idx:
                    continue
                si = s_idx[sid]
                for d in r_days:
                    for b in r.blocks:
                        if 0 <= d < D and 0 <= b < B:
                            t = d * B + b
                            if r.hard:
                                pb.forbidden.add((si, t))
                            else:
                                pb.soft_slot[(si, t)] = pb.soft_slot.get((si, t), 0) + AVOID_PENALTY
        elif r.type == "subject_prefer_morning":
            for sid in r.subjectIds:
                if sid in s_idx:
                    si = s_idx[sid]
                    for t in range(S):
                        pb.soft_slot[(si, t)] = pb.soft_slot.get((si, t), 0) + t % B

    # Validaciones estáticas
    for pi, t in enumerate(data.docentes):
        load = sum(it.hours for it in items if it.p == pi)
        avail = S - sum(1 for (p, _) in pb.unavailable if p == pi)
        if load > t.maxHorasSemana:
            issues.append(f"{t.nombre}: {load} h superan su límite de {t.maxHorasSemana} h.")
        if load > avail:
            issues.append(f"{t.nombre}: necesita {load} bloques pero solo tiene {avail} disponibles.")
    return pb
