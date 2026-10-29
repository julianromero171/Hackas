"""Evaluador independiente (fitness) de un horario en formato {cursoId: [asignaturaId|None por slot]}."""
from __future__ import annotations

from collections import Counter, defaultdict

from .problem import Problem


def evaluate(pb: Problem, horario: dict[str, list]) -> dict:
    D, B, S = pb.D, pb.B, pb.S
    item_of = {(it.course_id, it.subject_id): it for it in pb.items}
    teacher_slots: dict[int, Counter] = defaultdict(Counter)
    type_slots: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))

    hard = dict(teacherClashes=0, unavailability=0, roomConflicts=0, forbidden=0, hoursMismatch=0, unknown=0)
    fatigue_consec = fatigue_last = equity_excess = 0
    slot_penalty = 0.0

    for course in pb.data.cursos:
        row = horario.get(course.id, [None] * S)
        counts = Counter()
        for t, sid in enumerate(row[:S]):
            if sid is None:
                continue
            it = item_of.get((course.id, sid))
            if it is None:
                hard["unknown"] += 1
                continue
            counts[sid] += 1
            teacher_slots[it.p][t] += 1
            type_slots[it.type][t].append(it.size)
            if (it.p, t) in pb.unavailable:
                hard["unavailability"] += 1
            if (it.s, t) in pb.forbidden:
                hard["forbidden"] += 1
            slot_penalty += pb.soft_slot.get((it.s, t), 0)
        for it in (i for i in pb.items if i.course_id == course.id):
            if counts[it.subject_id] != it.hours:
                hard["hoursMismatch"] += abs(counts[it.subject_id] - it.hours)

        # fatiga y equidad
        heavy = [bool(sid and item_of.get((course.id, sid)) and item_of[(course.id, sid)].heavy) for sid in row[:S]]
        for d in range(D):
            per_subject = Counter(row[d * B + b] for b in range(B) if row[d * B + b])
            for sid, n in per_subject.items():
                it = item_of.get((course.id, sid))
                if it:
                    allowed = -(-it.hours // D)
                    equity_excess += max(0, n - allowed)
            for b in range(B):
                t = d * B + b
                if not heavy[t]:
                    continue
                if b == B - 1:
                    fatigue_last += 1
                elif b not in pb.break_after and heavy[t + 1]:
                    fatigue_consec += 1

    for p, cnt in teacher_slots.items():
        hard["teacherClashes"] += sum(n - 1 for n in cnt.values() if n > 1)

    for ty, slots in type_slots.items():
        caps = sorted(pb.type_caps.get(ty, []))
        for sizes in slots.values():
            used = [False] * len(caps)
            for sz in sorted(sizes, reverse=True):
                for i, cap in enumerate(caps):
                    if not used[i] and cap >= sz:
                        used[i] = True
                        break
                else:
                    hard["roomConflicts"] += 1

    gaps = 0
    for p, cnt in teacher_slots.items():
        for d in range(D):
            busy = [b for b in range(B) if cnt.get(d * B + b)]
            if busy:
                gaps += busy[-1] - busy[0] + 1 - len(busy)

    total_hard = sum(hard.values())
    return {
        "hard": {**hard, "total": total_hard},
        "gaps": gaps,
        "fatigue": {"consecutive": fatigue_consec, "lastBlock": fatigue_last, "total": fatigue_consec + fatigue_last},
        "equityExcess": equity_excess,
        "slotPenalty": slot_penalty,
        "feasible": total_hard == 0,
    }
