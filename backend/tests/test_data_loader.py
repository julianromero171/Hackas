"""Pruebas de la capa de datos (DataLoader) con un Excel sintético."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backend.data_loader import DataLoader, DataValidationError, normalizar_bool, normalizar_dia

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
BLOQUES = ["B1", "B2", "B3", "B4", "B5", "B6"]


def libro_base() -> dict[str, pd.DataFrame]:
    bloques = pd.DataFrame({
        "bloque_id": BLOQUES,
        "inicio": ["07:00", "07:50", "08:55", "09:45", "10:50", "11:40"],
        "fin": ["07:50", "08:40", "09:45", "10:35", "11:40", "12:30"],
    })
    cursos = pd.DataFrame({"curso_id": ["6A", "6B"], "nombre": ["6°A", "6°B"], "estudiantes": [32, 30]})
    docentes = pd.DataFrame({
        "docente_id": ["D01", "D02", "D03"],
        "nombre": ["Carlos Ruiz", "Laura Méndez", "Julián Ríos"],
        "max_sesiones_semana": [20, 20, 10],
    })
    carga = pd.DataFrame({
        "curso_id": ["6A", "6A", "6B", "6B", "6A"],
        "asignatura": ["Matemáticas", "Español", "Matemáticas", "Español", "Química"],
        "docente_principal_id": ["D01", "D02", "D01", "D02", "D03"],
        "sesiones_semana": [5, 4, 5, 4, 2],
        "tipo_salon_requerido": ["Aula", "Aula", "Aula", "Aula", "Laboratorio"],
    })
    salones = pd.DataFrame({
        "salon_id": ["S1", "S2", "L1"],
        "nombre": ["Aula 101", "Aula 102", "Lab Química"],
        "tipo": ["Aula", "Aula", "Laboratorio"],
        "capacidad": [35, 35, 36],
    })
    disp = pd.DataFrame(
        [(d, dia, b, 1) for d in ("D01", "D02", "D03") for dia in DIAS for b in BLOQUES],
        columns=["docente_id", "dia", "bloque_id", "disponible"],
    )
    cambio = pd.DataFrame({
        "docente_id": ["D02"] * 6,
        "dia": ["martes"] * 6,  # minúscula a propósito: debe normalizarse
        "bloque_id": BLOQUES,
        "disponible_nuevo": ["No"] * 6,
        "motivo": ["Cita médica"] * 6,
    })
    return {"Bloques": bloques, "Cursos": cursos, "Docentes": docentes, "Carga": carga,
            "Salones": salones, "Disponibilidad": disp, "Cambio": cambio}


def escribir_excel(libro: dict[str, pd.DataFrame], ruta: Path) -> Path:
    with pd.ExcelWriter(ruta, engine="openpyxl") as w:
        for hoja, df in libro.items():
            df.to_excel(w, sheet_name=hoja, index=False)
    return ruta


def test_normalizadores() -> None:
    assert normalizar_dia("MIERCOLES") == "Miércoles"
    assert normalizar_dia("mar") == "Martes"
    assert normalizar_bool("Sí") is True and normalizar_bool(0) is False and normalizar_bool("quizá") is None


def test_carga_excel_y_solver_data(tmp_path: Path) -> None:
    loader = DataLoader(escribir_excel(libro_base(), tmp_path / "datos.xlsx"))
    loader.cargar()
    rep = loader.validar()
    assert rep.ok, str(rep)

    datos = loader.preparar_para_solver()
    assert datos.dias == DIAS and [b.id for b in datos.bloques] == BLOQUES
    assert len(datos.disponibilidad) == 3 * 5 * 6  # rejilla completa
    # Cambio aplicado: D02 no disponible el martes, sí el lunes
    assert not any(datos.disponible("D02", "Martes", b) for b in BLOQUES)
    assert datos.disponible("D02", "Lunes", "B1")
    assert len(datos.cambios_aplicados) == 6 and datos.cambios_aplicados[0]["tipo"] == "actualizado"
    # Salones compatibles por tipo y capacidad
    quimica = next(r for r in datos.requerimientos if r.asignatura == "Química")
    assert datos.salones_compatibles[quimica.id] == ["L1"]


def test_aplicar_cambio_no_muta_y_agrega_filas() -> None:
    libro = libro_base()
    disp = libro["Disponibilidad"]
    disp_disperso = disp[~((disp.docente_id == "D02") & (disp.dia == "Martes") & (disp.bloque_id == "B6"))]
    original = disp_disperso.copy()

    loader = DataLoader()
    nuevo = loader.aplicar_cambio_disponibilidad(disp_disperso, libro["Cambio"])

    pd.testing.assert_frame_equal(disp_disperso, original)  # la entrada no cambia
    martes_d02 = nuevo[(nuevo.docente_id == "D02") & (nuevo.dia == "Martes")]
    assert len(martes_d02) == 6 and not martes_d02.disponible.any() and martes_d02.modificado.all()
    assert (martes_d02.motivo_cambio == "Cita médica").all()
    assert {c["tipo"] for c in loader.cambios_aplicados} == {"actualizado", "nuevo"}
    assert nuevo[~nuevo.modificado].disponible.all()


def test_detecta_errores() -> None:
    libro = libro_base()
    libro["Carga"].loc[0, "curso_id"] = "9Z"              # FK curso inexistente
    libro["Carga"].loc[1, "docente_principal_id"] = None   # ID nulo
    libro["Cursos"].loc[1, "estudiantes"] = 40             # 6B no cabe en ningún aula (máx 35)
    libro["Salones"]["capacidad"] = libro["Salones"]["capacidad"].astype(object)
    libro["Salones"].loc[0, "capacidad"] = "treinta"       # tipo inválido
    loader = DataLoader()
    loader.desde_dataframes(libro)
    rep = loader.validar()
    texto = "\n".join(rep.errores)
    assert "9Z" in texto
    assert "'docente_principal_id' nulo" in texto
    assert "'capacidad' debe ser entero" in texto
    with pytest.raises(DataValidationError):
        loader.preparar_para_solver()

    libro = libro_base()
    libro["Cursos"].loc[1, "estudiantes"] = 40
    loader.desde_dataframes(libro)
    assert any("capacidad suficiente" in e for e in loader.validar().errores)


def test_factibilidad_tras_cambio() -> None:
    libro = libro_base()
    libro["Docentes"].loc[2, "max_sesiones_semana"] = 1   # D03 tiene 2 sesiones
    loader = DataLoader()
    loader.desde_dataframes(libro)
    assert any("D03: carga 2 > máximo" in e for e in loader.validar().errores)


def test_alimenta_cpsat() -> None:
    """Las estructuras sirven directamente para un modelo CP-SAT factible."""
    from ortools.sat.python import cp_model

    loader = DataLoader()
    loader.desde_dataframes(libro_base())
    datos = loader.preparar_para_solver()

    m = cp_model.CpModel()
    x = {(r.id, d, b, s): m.NewBoolVar(f"x_{r.id}_{d}_{b}_{s}")
         for r in datos.requerimientos for d, b in datos.slots for s in datos.salones_compatibles[r.id]
         if datos.disponible(r.docente_id, d, b)}
    for r in datos.requerimientos:
        m.Add(sum(v for k, v in x.items() if k[0] == r.id) == r.sesiones_semana)
    for d, b in datos.slots:
        for grupo in (datos.requerimientos_por_curso(), datos.requerimientos_por_docente()):
            for reqs in grupo.values():
                ids = {r.id for r in reqs}
                m.Add(sum(v for k, v in x.items() if k[0] in ids and k[1] == d and k[2] == b) <= 1)
        for s in datos.salones:
            m.Add(sum(v for k, v in x.items() if k[3] == s and k[1] == d and k[2] == b) <= 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10
    assert solver.Solve(m) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    d02 = [k for k, v in x.items() if solver.Value(v) and datos.requerimientos[k[0]].docente_id == "D02"]
    assert all(k[1] != "Martes" for k in d02)
