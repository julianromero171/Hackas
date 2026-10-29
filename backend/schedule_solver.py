"""
Motor de optimización de horarios escolares con Google OR-Tools CP-SAT (`ScheduleSolver`).

Cumple la especificación técnica de la Hackathon Colombia 5.0 | Gnosoft:

Variables de decisión:
    X[c, a, d, s, dia, b] ∈ {0, 1}
        Indica si el Curso `c`, Asignatura `a`, Docente `d`, Salón `s`
        se dicta en el `dia` y Bloque `b`.

    pendiente[c, a] ∈ [0, sesiones_semana]
        Variable de holgura por (Curso, Asignatura) para garantizar factibilidad
        siempre y calcular `Cobertura %` y `Sesiones Pendientes`.

Restricciones duras (Hard Constraints):
    1. Máximo 1 sesión por (Curso, Día, Bloque).
    2. Máximo 1 sesión por (Docente, Día, Bloque).
    3. Máximo 1 sesión por (Salón, Día, Bloque).
    4. Disponibilidad docente: X[c,a,d,s,dia,b] = 0 si disponible(d, dia, b) == 0.
    5. Límite semanal por docente: Σ X[*, *, d, *, *, *] ≤ max_sesiones_semana(d).
    6. Salón compatible: tipo(s) == tipo_salon_requerido y capacidad(s) ≥ estudiantes(c).
    7. Cobertura con holgura: Σ_{d,s,dia,b} X[c,a,d,s,dia,b] + pendiente[c,a] == sesiones_semana(c,a).

Objetivos / Restricciones blandas (Soft Constraints):
    1. Maximizar el total de sesiones válidas asignadas (prioridad máxima).
    2. Penalizar días donde una asignatura se repita para el mismo curso (y bloques consecutivos).
    3. Penalizar huecos en la agenda diaria de los docentes (bloques libres entre la 1.ª y última clase del día).
    4. (En escenario Cambio) Minimizar perturbaciones respecto al horario base.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd
from ortools.sat.python import cp_model

from .data_loader import DataLoader, Requerimiento, SolverData


@dataclass(frozen=True)
class PesosObjetivo:
    """Pesos jerárquicos de la función objetivo en CP-SAT."""

    # Prioridad 1: asignar todas las sesiones requeridas (minimizar pendientes)
    peso_sesion_asignada: int = 1_000_000
    # Prioridad 2: evitar repetir la misma asignatura el mismo día para un curso
    penalizacion_repeticion_dia: int = 1_200
    # Prioridad 2b: evitar bloques consecutivos de la misma asignatura en el mismo día
    penalizacion_consecutivas: int = 800
    # Prioridad 3: minimizar huecos (ventanas) en la agenda diaria de cada docente
    penalizacion_hueco_docente: int = 400
    # Prioridad 4: preferir el docente principal de la fila Carga cuando existan alternativos
    penalizacion_docente_alternativo: int = 25
    # Prioridad 5 (solo re-optimización tras Cambio): conservar asignaciones del horario base
    bono_estabilidad_slot: int = 60
    bono_estabilidad_exacta: int = 20


class ScheduleSolver:
    """
    Motor CP-SAT que recibe `SolverData` (producido por `DataLoader`) y genera el horario óptimo
    junto con el reporte de métricas de la Hackathon Gnosoft.
    """

    def __init__(
        self,
        datos: SolverData,
        *,
        pesos: Optional[PesosObjetivo] = None,
        permitir_docentes_alternativos: bool = True,
        tiempo_maximo_seg: float = 15.0,
        num_workers: int = 8,
    ) -> None:
        self.datos = datos
        self.pesos = pesos or PesosObjetivo()
        self.permitir_docentes_alternativos = permitir_docentes_alternativos
        self.tiempo_maximo_seg = tiempo_maximo_seg
        self.num_workers = num_workers

    # ------------------------------------------------------------------ #
    # Construcción y resolución del modelo CP-SAT
    # ------------------------------------------------------------------ #
    def resolver(
        self,
        *,
        horario_referencia: Optional[pd.DataFrame] = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """
        Construye y resuelve el modelo CP-SAT.

        :param horario_referencia: DataFrame de asignaciones previas (opcional). Si se entrega,
               añade un bono suave de estabilidad para mover solo las sesiones necesarias.
        :return: (df_asignaciones, metricas)
        """
        t0 = time.perf_counter()
        model = cp_model.CpModel()
        d = self.datos
        pesos = self.pesos
        n_bloques = len(d.bloques)

        # ------------------------------------------------------------------
        # 1. Variables de decisión X[c, a, doc, s, dia, b] ∈ {0, 1}
        #    Solo se instancian tuplas que cumplen disponibilidad docente y
        #    compatibilidad de salón (equivale a fijar X = 0 en las demás).
        # ------------------------------------------------------------------
        X: dict[tuple[str, str, str, str, str, str], cp_model.IntVar] = {}
        vars_por_req: dict[int, list[cp_model.IntVar]] = {r.id: [] for r in d.requerimientos}
        vars_por_req_dia: dict[tuple[int, str], list[cp_model.IntVar]] = {}
        vars_por_req_dia_blq: dict[tuple[int, str, int], list[cp_model.IntVar]] = {}
        vars_por_curso_slot: dict[tuple[str, str, str], list[cp_model.IntVar]] = {}
        vars_por_docente_slot: dict[tuple[str, str, str], list[cp_model.IntVar]] = {}
        vars_por_salon_slot: dict[tuple[str, str, str], list[cp_model.IntVar]] = {}
        vars_por_docente: dict[str, list[cp_model.IntVar]] = {doc_id: [] for doc_id in d.docentes}
        vars_docente_alternativo: list[cp_model.IntVar] = []
        terminos_desempate_salon: list[cp_model.LinearExpr] = []
        orden_cursos = {cid: idx for idx, cid in enumerate(d.cursos)}

        for req in d.requerimientos:
            c = req.curso_id
            a = req.asignatura
            idx_c = orden_cursos.get(c, 0)
            docentes_cand = (
                d.docentes_compatibles.get(req.id, [req.docente_id])
                if self.permitir_docentes_alternativos
                else [req.docente_id]
            )
            salones_cand = d.salones_compatibles.get(req.id, [])
            # Ordenar salones candidatos priorizando el aula propia del curso (ej. "Aula 7A" para "7A")
            salones_ordenados = sorted(
                salones_cand,
                key=lambda sid: (
                    0 if c.lower() in d.salones[sid].nombre.lower() else 1,
                    abs(idx_c - salones_cand.index(sid)),
                    sid,
                ),
            )

            for doc_id in docentes_cand:
                es_alternativo = doc_id != req.docente_id
                for dia in d.dias:
                    for blq in d.bloques:
                        b = blq.id
                        # Regla obligatoria: solo asignar si disponible == 1
                        if not d.disponible(doc_id, dia, b):
                            continue
                        for rank_s, s_id in enumerate(salones_ordenados):
                            key = (c, a, doc_id, s_id, dia, b)
                            var = model.NewBoolVar(f"X_{c}_{req.id}_{doc_id}_{s_id}_{dia}_{b}")
                            X[key] = var

                            vars_por_req[req.id].append(var)
                            vars_por_req_dia.setdefault((req.id, dia), []).append(var)
                            vars_por_req_dia_blq.setdefault((req.id, dia, blq.indice), []).append(var)
                            vars_por_curso_slot.setdefault((c, dia, b), []).append(var)
                            vars_por_docente_slot.setdefault((doc_id, dia, b), []).append(var)
                            vars_por_salon_slot.setdefault((s_id, dia, b), []).append(var)
                            vars_por_docente[doc_id].append(var)
                            if es_alternativo:
                                vars_docente_alternativo.append(var)
                            if rank_s > 0:
                                terminos_desempate_salon.append(rank_s * var)

        # ------------------------------------------------------------------
        # 2. Restricciones duras (Hard Constraints)
        # ------------------------------------------------------------------
        # 2a. No colisión de cursos: máximo 1 sesión por (curso, día, bloque)
        for vars_slot in vars_por_curso_slot.values():
            if len(vars_slot) > 1:
                model.AddAtMostOne(vars_slot)

        # 2b. No colisión de docentes: máximo 1 sesión por (docente, día, bloque)
        for vars_slot in vars_por_docente_slot.values():
            if len(vars_slot) > 1:
                model.AddAtMostOne(vars_slot)

        # 2c. No colisión de salones: máximo 1 sesión por (salón, día, bloque)
        for vars_slot in vars_por_salon_slot.values():
            if len(vars_slot) > 1:
                model.AddAtMostOne(vars_slot)

        # 2d. Límite máximo de sesiones semanales por docente
        for doc_id, doc in d.docentes.items():
            if vars_por_docente[doc_id]:
                model.Add(sum(vars_por_docente[doc_id]) <= doc.max_sesiones_semana)

        # 2e. Intensidad semanal por (Curso, Asignatura) + variable de holgura (pendientes)
        pendiente_por_req: dict[int, cp_model.IntVar] = {}
        for req in d.requerimientos:
            holgura = model.NewIntVar(0, req.sesiones_semana, f"pendiente_{req.curso_id}_{req.id}")
            pendiente_por_req[req.id] = holgura
            model.Add(sum(vars_por_req[req.id]) + holgura == req.sesiones_semana)

        # ------------------------------------------------------------------
        # 3. Restricciones blandas (Soft Constraints)
        # ------------------------------------------------------------------
        terminos_penalizacion: list[cp_model.LinearExpr] = []

        # 3a. Penalizar días donde una asignatura se repita para el mismo curso
        #     y penalizar bloques consecutivos de la misma asignatura
        vars_repeticion_dia: list[cp_model.IntVar] = []
        vars_consecutivas: list[cp_model.IntVar] = []

        for req in d.requerimientos:
            for dia in d.dias:
                vars_dia = vars_por_req_dia.get((req.id, dia), [])
                if len(vars_dia) <= 1:
                    continue
                # Exceso sobre 1 sesión diaria de la misma asignatura en el mismo curso
                exceso_dia = model.NewIntVar(0, req.sesiones_semana, f"rep_{req.id}_{dia}")
                model.Add(exceso_dia >= sum(vars_dia) - 1)
                vars_repeticion_dia.append(exceso_dia)

                # Bloques consecutivos b y b+1 en el mismo día
                for idx_b in range(n_bloques - 1):
                    v_actual = vars_por_req_dia_blq.get((req.id, dia, idx_b), [])
                    v_sig = vars_por_req_dia_blq.get((req.id, dia, idx_b + 1), [])
                    if v_actual and v_sig:
                        consec = model.NewBoolVar(f"consec_{req.id}_{dia}_{idx_b}")
                        model.Add(consec >= sum(v_actual) + sum(v_sig) - 1)
                        vars_consecutivas.append(consec)

        if vars_repeticion_dia:
            terminos_penalizacion.append(pesos.penalizacion_repeticion_dia * sum(vars_repeticion_dia))
        if vars_consecutivas:
            terminos_penalizacion.append(pesos.penalizacion_consecutivas * sum(vars_consecutivas))

        # 3b. Penalizar huecos en la agenda diaria de los docentes
        #     Para cada (docente, día):
        #       activo[b] = Σ_{c,a,s} X[c,a,d,s,dia,b] ∈ {0, 1}
        #       Si hay clases ese día, span = ultimo_bloque - primer_bloque + 1
        #       huecos = span - Σ_b activo[b]
        vars_huecos_docente: list[cp_model.IntVar] = []
        for doc_id in d.docentes:
            for dia in d.dias:
                activos_dia: list[cp_model.IntVar] = []
                indices_con_vars: list[int] = []
                for blq in d.bloques:
                    v_slot = vars_por_docente_slot.get((doc_id, dia, blq.id), [])
                    if not v_slot:
                        continue
                    act = model.NewBoolVar(f"act_{doc_id}_{dia}_{blq.id}")
                    model.Add(act == sum(v_slot))
                    activos_dia.append(act)
                    indices_con_vars.append(blq.indice)

                if len(activos_dia) <= 1:
                    continue

                primero = model.NewIntVar(0, n_bloques - 1, f"prim_{doc_id}_{dia}")
                ultimo = model.NewIntVar(0, n_bloques - 1, f"ult_{doc_id}_{dia}")
                span = model.NewIntVar(0, n_bloques, f"span_{doc_id}_{dia}")
                huecos = model.NewIntVar(0, n_bloques, f"huecos_{doc_id}_{dia}")

                for act, idx_b in zip(activos_dia, indices_con_vars):
                    model.Add(ultimo >= idx_b).OnlyEnforceIf(act)
                    model.Add(primero <= idx_b).OnlyEnforceIf(act)

                model.Add(span >= ultimo - primero + 1)
                model.Add(huecos >= span - sum(activos_dia))
                vars_huecos_docente.append(huecos)

        if vars_huecos_docente:
            terminos_penalizacion.append(pesos.penalizacion_hueco_docente * sum(vars_huecos_docente))

        # 3c. Preferencia suave por el docente principal de Carga
        if vars_docente_alternativo and pesos.penalizacion_docente_alternativo > 0:
            terminos_penalizacion.append(
                pesos.penalizacion_docente_alternativo * sum(vars_docente_alternativo)
            )
        if terminos_desempate_salon:
            terminos_penalizacion.append(sum(terminos_desempate_salon))

        # 3d. Bono de estabilidad respecto a un horario de referencia (para hoja Cambio)
        bono_estabilidad: list[cp_model.LinearExpr] = []
        if horario_referencia is not None and not horario_referencia.empty:
            slots_ref = set(
                zip(
                    horario_referencia["curso_id"],
                    horario_referencia["asignatura"],
                    horario_referencia["dia"],
                    horario_referencia["bloque_id"],
                )
            )
            exactos_ref = set(
                zip(
                    horario_referencia["curso_id"],
                    horario_referencia["asignatura"],
                    horario_referencia["docente_id"],
                    horario_referencia["salon_id"],
                    horario_referencia["dia"],
                    horario_referencia["bloque_id"],
                )
            )
            vars_mismo_slot = [
                var for (c, a, _doc, _s, dia, b), var in X.items()
                if (c, a, dia, b) in slots_ref
            ]
            vars_exactas = [
                var for key, var in X.items()
                if key in exactos_ref
            ]
            if vars_mismo_slot:
                bono_estabilidad.append(pesos.bono_estabilidad_slot * sum(vars_mismo_slot))
            if vars_exactas:
                bono_estabilidad.append(pesos.bono_estabilidad_exacta * sum(vars_exactas))

        # ------------------------------------------------------------------
        # 4. Función objetivo: maximizar sesiones válidas - penalizaciones
        # ------------------------------------------------------------------
        total_sesiones_requeridas = sum(r.sesiones_semana for r in d.requerimientos)
        sesiones_asignadas_expr = total_sesiones_requeridas - sum(pendiente_por_req.values())

        model.Maximize(
            pesos.peso_sesion_asignada * sesiones_asignadas_expr
            - sum(terminos_penalizacion)
            + sum(bono_estabilidad)
        )

        # ------------------------------------------------------------------
        # 5. Ejecución del solver
        # ------------------------------------------------------------------
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(self.tiempo_maximo_seg)
        solver.parameters.num_search_workers = int(self.num_workers)

        status = solver.Solve(model)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        status_name = solver.StatusName(status)

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            df_vacio = pd.DataFrame(
                columns=[
                    "curso_id", "asignatura", "docente_id", "docente_nombre",
                    "salon_id", "salon_nombre", "tipo_salon", "dia", "bloque_id", "inicio", "fin",
                ]
            )
            metricas = self.calcular_metricas(df_vacio, estado_solver=status_name, tiempo_ms=elapsed_ms)
            return df_vacio, metricas

        # ------------------------------------------------------------------
        # 6. Extracción del DataFrame de asignaciones
        # ------------------------------------------------------------------
        bloques_map = {b.id: b for b in d.bloques}
        filas: list[dict[str, Any]] = []
        for (c, a, doc_id, s_id, dia, b), var in X.items():
            if solver.Value(var) == 1:
                blq = bloques_map[b]
                doc = d.docentes[doc_id]
                sal = d.salones[s_id]
                filas.append({
                    "curso_id": c,
                    "asignatura": a,
                    "docente_id": doc_id,
                    "docente_nombre": doc.nombre,
                    "salon_id": s_id,
                    "salon_nombre": sal.nombre,
                    "tipo_salon": sal.tipo,
                    "dia": dia,
                    "bloque_id": b,
                    "inicio": blq.inicio.strftime("%H:%M"),
                    "fin": blq.fin.strftime("%H:%M"),
                })

        df_asig = pd.DataFrame(filas)
        if not df_asig.empty:
            df_asig = df_asig.sort_values(
                by=["curso_id", "dia", "bloque_id"],
                key=lambda s: (
                    s.map(d.idx_dia) if s.name == "dia"
                    else (s.map(d.idx_bloque) if s.name == "bloque_id" else s)
                ),
            ).reset_index(drop=True)

        metricas = self.calcular_metricas(df_asig, estado_solver=status_name, tiempo_ms=elapsed_ms)
        return df_asig, metricas

    # ------------------------------------------------------------------ #
    # Evaluación independiente de métricas y auditoría de reglas
    # ------------------------------------------------------------------ #
    def calcular_metricas(
        self,
        df_asignaciones: pd.DataFrame,
        *,
        estado_solver: str = "EVALUATED",
        tiempo_ms: float = 0.0,
    ) -> dict[str, Any]:
        """
        Calcula todas las métricas oficiales de la guía Gnosoft:
          - Cobertura % = sesiones válidas asignadas / sesiones requeridas × 100
          - Colisiones (por curso, docente y salón)
          - Sesiones Pendientes (total y desglose por curso/asignatura)
          - Huecos Docentes (total y por docente)
          - Repeticiones en el mismo día y sesiones consecutivas por curso
        """
        d = self.datos
        requeridas_total = sum(r.sesiones_semana for r in d.requerimientos)

        if df_asignaciones is None or df_asignaciones.empty:
            detalle_pend = [
                {
                    "curso_id": r.curso_id,
                    "asignatura": r.asignatura,
                    "docente_principal_id": r.docente_id,
                    "requeridas": r.sesiones_semana,
                    "asignadas_validas": 0,
                    "pendientes": r.sesiones_semana,
                }
                for r in d.requerimientos
            ]
            return {
                "Cobertura %": 0.0,
                "Sesiones Requeridas": requeridas_total,
                "Sesiones Asignadas": 0,
                "Sesiones Válidas": 0,
                "Colisiones": 0,
                "Detalle Colisiones": {"curso": 0, "docente": 0, "salon": 0},
                "Infracciones Disponibilidad": 0,
                "Infracciones Salón": 0,
                "Sesiones Pendientes": requeridas_total,
                "Detalle Pendientes": detalle_pend,
                "Huecos Docentes": 0,
                "Huecos por Docente": {doc_id: 0 for doc_id in d.docentes},
                "Repeticiones Mismo Día": 0,
                "Sesiones Consecutivas": 0,
                "Carga por Docente": {doc_id: 0 for doc_id in d.docentes},
                "Estado Solver": estado_solver,
                "Tiempo (ms)": tiempo_ms,
            }

        df = df_asignaciones.copy()

        # 1. Colisiones: cada par de asignaciones que comparte curso, docente o salón en el mismo (día, bloque)
        def _contar_pares_colision(col: str) -> tuple[int, set[int]]:
            pares = 0
            filas_en_colision: set[int] = set()
            for _, grp in df.groupby([col, "dia", "bloque_id"]):
                n = len(grp)
                if n > 1:
                    pares += n * (n - 1) // 2
                    filas_en_colision.update(grp.index.tolist())
            return pares, filas_en_colision

        col_curso, idx_col_curso = _contar_pares_colision("curso_id")
        col_docente, idx_col_doc = _contar_pares_colision("docente_id")
        col_salon, idx_col_salon = _contar_pares_colision("salon_id")
        total_colisiones = col_curso + col_docente + col_salon

        # 2. Verificar validez individual de cada fila (disponibilidad, salón y docente habilitado)
        req_map: dict[tuple[str, str], Requerimiento] = {
            (r.curso_id, r.asignatura): r for r in d.requerimientos
        }
        infracciones_disp = 0
        infracciones_salon = 0
        filas_invalidas: set[int] = idx_col_curso | idx_col_doc | idx_col_salon

        for idx, fila in df.iterrows():
            c = fila["curso_id"]
            a = fila["asignatura"]
            doc_id = fila["docente_id"]
            s_id = fila["salon_id"]
            dia = fila["dia"]
            b = fila["bloque_id"]

            if not d.disponible(doc_id, dia, b):
                infracciones_disp += 1
                filas_invalidas.add(idx)

            req = req_map.get((c, a))
            if req is None:
                filas_invalidas.add(idx)
                continue

            if s_id not in d.salones_compatibles.get(req.id, []):
                infracciones_salon += 1
                filas_invalidas.add(idx)

            if doc_id not in d.docentes_compatibles.get(req.id, [req.docente_id]):
                filas_invalidas.add(idx)

        df_validas = df.drop(index=list(filas_invalidas))

        # 3. Cobertura y Sesiones Pendientes (sin contar asignaciones sobrantes)
        conteo_validas = df_validas.groupby(["curso_id", "asignatura"]).size().to_dict()
        sesiones_validas_efectivas = 0
        detalle_pendientes: list[dict[str, Any]] = []

        for req in d.requerimientos:
            n_val = min(int(conteo_validas.get((req.curso_id, req.asignatura), 0)), req.sesiones_semana)
            sesiones_validas_efectivas += n_val
            pend = req.sesiones_semana - n_val
            if pend > 0:
                detalle_pendientes.append({
                    "curso_id": req.curso_id,
                    "asignatura": req.asignatura,
                    "docente_principal_id": req.docente_id,
                    "requeridas": req.sesiones_semana,
                    "asignadas_validas": n_val,
                    "pendientes": pend,
                })

        sesiones_pendientes = requeridas_total - sesiones_validas_efectivas
        cobertura_pct = round((sesiones_validas_efectivas / requeridas_total) * 100.0, 2) if requeridas_total else 100.0

        # 4. Huecos docentes (bloques libres entre la primera y la última clase del docente en un mismo día)
        huecos_por_docente: dict[str, int] = {doc_id: 0 for doc_id in d.docentes}
        for (doc_id, _dia), grp in df.groupby(["docente_id", "dia"]):
            indices = sorted({d.idx_bloque[b] for b in grp["bloque_id"] if b in d.idx_bloque})
            if len(indices) >= 2:
                span = indices[-1] - indices[0] + 1
                huecos_por_docente[doc_id] = huecos_por_docente.get(doc_id, 0) + (span - len(indices))
        total_huecos = sum(huecos_por_docente.values())

        # 5. Repeticiones de asignatura el mismo día y sesiones consecutivas por curso
        repeticiones_dia = 0
        sesiones_consecutivas = 0
        for (_c, _a, _dia), grp in df.groupby(["curso_id", "asignatura", "dia"]):
            indices = sorted({d.idx_bloque[b] for b in grp["bloque_id"] if b in d.idx_bloque})
            if len(indices) > 1:
                repeticiones_dia += len(indices) - 1
                for i in range(len(indices) - 1):
                    if indices[i + 1] - indices[i] == 1:
                        sesiones_consecutivas += 1

        carga_por_docente = {
            doc_id: int((df["docente_id"] == doc_id).sum()) for doc_id in d.docentes
        }

        return {
            "Cobertura %": cobertura_pct,
            "Sesiones Requeridas": requeridas_total,
            "Sesiones Asignadas": int(len(df)),
            "Sesiones Válidas": sesiones_validas_efectivas,
            "Colisiones": total_colisiones,
            "Detalle Colisiones": {
                "curso": col_curso,
                "docente": col_docente,
                "salon": col_salon,
            },
            "Infracciones Disponibilidad": infracciones_disp,
            "Infracciones Salón": infracciones_salon,
            "Sesiones Pendientes": sesiones_pendientes,
            "Detalle Pendientes": detalle_pendientes,
            "Huecos Docentes": total_huecos,
            "Huecos por Docente": huecos_por_docente,
            "Repeticiones Mismo Día": repeticiones_dia,
            "Sesiones Consecutivas": sesiones_consecutivas,
            "Carga por Docente": carga_por_docente,
            "Estado Solver": estado_solver,
            "Tiempo (ms)": tiempo_ms,
        }


# --------------------------------------------------------------------------- #
# Funciones de alto nivel: flujo Base + Escenario de Cambio (hoja Cambio)
# --------------------------------------------------------------------------- #
def comparar_horarios(
    df_base: pd.DataFrame,
    df_nuevo: pd.DataFrame,
    cambios_disponibilidad: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """
    Compara el horario base con el horario regenerado tras aplicar la hoja `Cambio`.
    Identifica:
      - Sesiones directamente afectadas en el horario base por el bloqueo (ej. D2 el martes).
      - Sesiones movidas de día/bloque o reasignadas de docente/salón.
    """
    slots_bloqueados: set[tuple[str, str, str]] = set()
    for c in cambios_disponibilidad or []:
        if c.get("despues") is False:
            slots_bloqueados.add((c["docente_id"], c["dia"], c["bloque_id"]))

    afectadas_directas: list[dict[str, Any]] = []
    if not df_base.empty and slots_bloqueados:
        for _, fila in df_base.iterrows():
            if (fila["docente_id"], fila["dia"], fila["bloque_id"]) in slots_bloqueados:
                afectadas_directas.append({
                    "curso_id": fila["curso_id"],
                    "asignatura": fila["asignatura"],
                    "docente_id": fila["docente_id"],
                    "salon_id": fila["salon_id"],
                    "dia_anterior": fila["dia"],
                    "bloque_anterior": fila["bloque_id"],
                })

    # Comparar por (curso_id, asignatura): qué sesiones cambiaron de (dia, bloque)
    movimientos: list[dict[str, Any]] = []
    claves_ca = sorted(
        set(zip(df_base.get("curso_id", []), df_base.get("asignatura", [])))
        | set(zip(df_nuevo.get("curso_id", []), df_nuevo.get("asignatura", [])))
    )

    for c, a in claves_ca:
        sub_b = df_base[(df_base["curso_id"] == c) & (df_base["asignatura"] == a)] if not df_base.empty else pd.DataFrame()
        sub_n = df_nuevo[(df_nuevo["curso_id"] == c) & (df_nuevo["asignatura"] == a)] if not df_nuevo.empty else pd.DataFrame()

        slots_b = {(r.dia, r.bloque_id): r for r in sub_b.itertuples()}
        slots_n = {(r.dia, r.bloque_id): r for r in sub_n.itertuples()}

        salen = [slots_b[k] for k in sorted(set(slots_b) - set(slots_n))]
        entran = [slots_n[k] for k in sorted(set(slots_n) - set(slots_b))]

        for r_ant, r_nue in zip(salen, entran):
            movimientos.append({
                "curso_id": c,
                "asignatura": a,
                "de_dia": r_ant.dia,
                "de_bloque": r_ant.bloque_id,
                "de_docente": r_ant.docente_id,
                "de_salon": r_ant.salon_id,
                "a_dia": r_nue.dia,
                "a_bloque": r_nue.bloque_id,
                "a_docente": r_nue.docente_id,
                "a_salon": r_nue.salon_id,
                "motivo": (
                    "Indisponibilidad docente (Cambio)"
                    if (r_ant.docente_id, r_ant.dia, r_ant.bloque_id) in slots_bloqueados
                    else "Reajuste por encadenamiento"
                ),
            })

    return {
        "Sesiones Afectadas por Cambio": len(afectadas_directas),
        "Detalle Sesiones Afectadas": afectadas_directas,
        "Sesiones Movidas": len(movimientos),
        "Detalle Sesiones Movidas": movimientos,
    }


def ejecutar_tras_cambio(
    loader: DataLoader,
    *,
    df_horario_base: Optional[pd.DataFrame] = None,
    pesos: Optional[PesosObjetivo] = None,
    permitir_docentes_alternativos: bool = True,
    tiempo_maximo_seg: float = 15.0,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Re-ejecuta el solver tras aplicar dinámicamente la hoja `Cambio` del `DataLoader`
    (ej. D2/D02 no disponible el martes) y retorna `(df_nuevo, metricas_con_comparacion)`.

    Si no se entrega `df_horario_base`, primero resuelve el escenario base (`aplicar_cambio=False`)
    para poder reportar con exactitud qué sesiones fueron afectadas y movidas.
    """
    if not loader.hojas:
        loader.cargar()

    if df_horario_base is None:
        datos_base = loader.preparar_para_solver(aplicar_cambio=False)
        solver_base = ScheduleSolver(
            datos_base,
            pesos=pesos,
            permitir_docentes_alternativos=permitir_docentes_alternativos,
            tiempo_maximo_seg=tiempo_maximo_seg,
        )
        df_horario_base, _ = solver_base.resolver()

    datos_cambio = loader.preparar_para_solver(aplicar_cambio=True)
    solver_cambio = ScheduleSolver(
        datos_cambio,
        pesos=pesos,
        permitir_docentes_alternativos=permitir_docentes_alternativos,
        tiempo_maximo_seg=tiempo_maximo_seg,
    )
    df_nuevo, metricas_cambio = solver_cambio.resolver(horario_referencia=df_horario_base)

    comparacion = comparar_horarios(df_horario_base, df_nuevo, datos_cambio.cambios_aplicados)
    metricas_cambio.update(comparacion)
    metricas_cambio["Cambios Disponibilidad Aplicados"] = len(datos_cambio.cambios_aplicados)
    return df_nuevo, metricas_cambio
