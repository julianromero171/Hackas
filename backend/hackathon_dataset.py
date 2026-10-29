"""
Conjunto de datos oficial de prueba de la Hackathon Colombia 5.0 | Gnosoft
("Generación inteligente de horarios escolares").

Permite construir los DataFrames o exportar el archivo `data/hackathon_gnosoft.xlsx`
exactamente con las hojas:
    Leeme, Bloques, Cursos, Docentes, Habilitados, Carga, Salones, Disponibilidad, Cambio
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd


def construir_libro_hackathon() -> dict[str, pd.DataFrame]:
    leeme = pd.DataFrame([
        ("Caso", "Datos ficticios: 6A, 6B, 7A y 7B, 30 sesiones semanales por curso; 120 sesiones en total."),
        ("Unidad", "Cada hora académica es un bloque de 50 minutos, no una hora de 60 minutos."),
        ("Jornada", "Lunes a viernes, B1 a B6; cada curso ocupa los 30 bloques."),
        ("Carga", "Cada curso tiene 30 sesiones semanales; las asignaturas tienen intensidades de 1, 2, 3 o 4 sesiones."),
        ("Docentes", "Los docentes solo están habilitados para las asignaturas indicadas. Inglés puede ser asignado a D4 o D6."),
        ("Regla docente", "Una clase debe usar un docente habilitado y disponible, sin cruces."),
        ("Alternativas", "En inglés se permite asignar D4 o D6; respetar disponibilidad, capacidad máxima y evitar cruces."),
        ("Salones", "La categoría GENERAL usa salón GENERAL; otras requieren el tipo indicado. Capacidad debe cubrir al curso."),
        ("Disponibilidad", "Una fila por docente, día y bloque: 1 disponible; 0 no disponible."),
        ("Cambio", "En el escenario adicional D2 no está disponible el martes. No altera los datos del caso base."),
        ("Solución de referencia", "Se verificó una solución factible para el caso base. También se verificó una solución con D2 no disponible el martes."),
        ("Privacidad", "Los nombres y datos son simulados."),
    ], columns=["Concepto", "Descripción"])

    bloques = pd.DataFrame([
        ("B1", "07:00:00", "08:00:00"),
        ("B2", "08:00:00", "09:00:00"),
        ("B3", "09:00:00", "10:00:00"),
        ("B4", "10:00:00", "11:00:00"),
        ("B5", "11:00:00", "12:00:00"),
        ("B6", "12:00:00", "13:00:00"),
    ], columns=["bloque_id", "inicio", "fin"])

    cursos = pd.DataFrame([
        ("7A", "7A", 30),
        ("7B", "7B", 28),
        ("6A", "6A", 30),
        ("6B", "6B", 28),
    ], columns=["curso_id", "nombre", "estudiantes"])

    docentes = pd.DataFrame([
        ("D1", "Ana Torres", 24),
        ("D2", "Luis Vega", 24),
        ("D3", "Marta Ruiz", 24),
        ("D4", "Carlos Peña", 24),
        ("D5", "Diana Rojas", 24),
        ("D6", "Andrés Castro", 24),
    ], columns=["docente_id", "nombre", "max_sesiones_semana"])

    habilitados = pd.DataFrame([
        ("Matemáticas", "D1", 1),
        ("Lenguaje", "D2", 1),
        ("Ciencias naturales", "D3", 1),
        ("Ciencias sociales", "D3", 1),
        ("Inglés", "D4", 1),
        ("Inglés", "D6", 1),
        ("Educación física", "D4", 1),
        ("Tecnología e informática", "D1", 1),
        ("Educación artística", "D6", 1),
        ("Ética y valores", "D5", 1),
        ("Educación religiosa", "D5", 1),
    ], columns=["asignatura", "docente_id", "habilitado"])

    plantilla_curso = [
        ("Matemáticas", "D1", 4, "GENERAL"),
        ("Lenguaje", "D2", 4, "GENERAL"),
        ("Ciencias naturales", "D3", 3, "LAB_CIENCIAS"),
        ("Ciencias sociales", "D3", 3, "GENERAL"),
        ("Inglés", "D4", 4, "GENERAL"),
        ("Educación física", "D4", 3, "CANCHA"),
        ("Tecnología e informática", "D1", 2, "SALA_INFORMATICA"),
        ("Educación artística", "D6", 3, "GENERAL"),
        ("Ética y valores", "D5", 1, "GENERAL"),
        ("Educación religiosa", "D5", 3, "GENERAL"),
    ]
    filas_carga = [
        (curso_id, asig, doc_id, ses, tipo)
        for curso_id in ("7A", "7B", "6A", "6B")
        for (asig, doc_id, ses, tipo) in plantilla_curso
    ]
    carga = pd.DataFrame(
        filas_carga,
        columns=["curso_id", "asignatura", "docente_principal_id", "sesiones_semana", "tipo_salon_requerido"],
    )

    salones = pd.DataFrame([
        ("A1", "Aula 7A", "GENERAL", 35),
        ("A2", "Aula 7B", "GENERAL", 32),
        ("L1", "Laboratorio 1", "LAB_CIENCIAS", 32),
        ("L2", "Laboratorio 2", "LAB_CIENCIAS", 32),
        ("C1", "Cancha 1", "CANCHA", 35),
        ("C2", "Cancha 2", "CANCHA", 32),
        ("I1", "Informática 1", "SALA_INFORMATICA", 32),
        ("I2", "Informática 2", "SALA_INFORMATICA", 30),
        ("A3", "Aula 6A", "GENERAL", 35),
        ("A4", "Aula 6B", "GENERAL", 32),
        ("L3", "Laboratorio 3", "LAB_CIENCIAS", 32),
        ("L4", "Laboratorio 4", "LAB_CIENCIAS", 32),
        ("C3", "Cancha 3", "CANCHA", 35),
        ("C4", "Cancha 4", "CANCHA", 32),
        ("I3", "Informática 3", "SALA_INFORMATICA", 32),
        ("I4", "Informática 4", "SALA_INFORMATICA", 30),
    ], columns=["salon_id", "nombre", "tipo", "capacidad"])

    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
    bloques_ids = ["B1", "B2", "B3", "B4", "B5", "B6"]
    filas_disp = []
    for doc_id in ("D1", "D2", "D3", "D4", "D5", "D6"):
        for dia in dias:
            for b in bloques_ids:
                disp_val = 0 if (doc_id == "D1" and dia == "Viernes" and b == "B6") else 1
                filas_disp.append((doc_id, dia, b, disp_val))
    disponibilidad = pd.DataFrame(filas_disp, columns=["docente_id", "dia", "bloque_id", "disponible"])

    cambio = pd.DataFrame([
        ("D2", "Martes", b, 0, "Indisponibilidad adicional")
        for b in bloques_ids
    ], columns=["docente_id", "dia", "bloque_id", "disponible_nuevo", "motivo"])

    return {
        "Leeme": leeme,
        "Bloques": bloques,
        "Cursos": cursos,
        "Docentes": docentes,
        "Habilitados": habilitados,
        "Carga": carga,
        "Salones": salones,
        "Disponibilidad": disponibilidad,
        "Cambio": cambio,
    }


def guardar_excel_hackathon(ruta: str | Path) -> Path:
    destino = Path(ruta)
    destino.parent.mkdir(parents=True, exist_ok=True)
    libro = construir_libro_hackathon()
    with pd.ExcelWriter(destino, engine="openpyxl") as writer:
        for nombre, df in libro.items():
            df.to_excel(writer, sheet_name=nombre, index=False)
    return destino


if __name__ == "__main__":
    out = guardar_excel_hackathon(Path(__file__).resolve().parent.parent / "data" / "hackathon_gnosoft.xlsx")
    print(f"Archivo Excel generado en: {out}")
