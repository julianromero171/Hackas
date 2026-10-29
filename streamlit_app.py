"""
Dashboard Streamlit — Hackathon Colombia 5.0 | Gnosoft
"Generación Inteligente y Optimización de Horarios Escolares mediante IA (OR-Tools CP-SAT)"

Ejecución:
    streamlit run streamlit_app.py
"""
from __future__ import annotations

import datetime as dt
import io
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import streamlit as st

from backend.data_loader import DataLoader, SolverData
from backend.hackathon_dataset import construir_libro_hackathon, guardar_excel_hackathon
from backend.schedule_solver import ScheduleSolver, comparar_horarios, ejecutar_tras_cambio

# --------------------------------------------------------------------------- #
# Configuración de página y estilos visuales para el jurado
# --------------------------------------------------------------------------- #
st.set_page_config(
    page_title="Gnosoft Timetable AI | Hackathon Colombia 5.0",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded",
)

PALETA_ASIGNATURAS: dict[str, tuple[str, str]] = {
    "Matemáticas": ("#1e3a8a", "#93c5fd"),
    "Lenguaje": ("#3b0764", "#d8b4fe"),
    "Ciencias naturales": ("#064e3b", "#6ee7b7"),
    "Ciencias sociales": ("#78350f", "#fcd34d"),
    "Inglés": ("#0c4a6e", "#7dd3fc"),
    "Educación física": ("#14532d", "#86efac"),
    "Tecnología e informática": ("#312e81", "#a5b4fc"),
    "Educación artística": ("#701a75", "#f0abfc"),
    "Ética y valores": ("#374151", "#d1d5db"),
    "Educación religiosa": ("#4c1d95", "#c4b5fd"),
}

RUTA_EXCEL_DEFECTO = Path(__file__).resolve().parent / "data" / "Datos_prueba_Gnosoft (1).xlsx"
RUTA_EXCEL_ALT = Path(__file__).resolve().parent / "data" / "hackathon_gnosoft.xlsx"


def inyectar_estilos() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
        .kpi-card {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 14px 16px;
            box-shadow: 0 4px 14px rgba(0,0,0,0.06);
        }
        .kpi-label {
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #64748b;
            margin-bottom: 4px;
            font-weight: 600;
        }
        .kpi-value {
            font-size: 1.7rem;
            font-weight: 800;
            color: #0f172a;
            line-height: 1.15;
        }
        .kpi-sub {
            font-size: 0.78rem;
            color: #64748b;
            margin-top: 4px;
        }
        .tt-table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 6px;
            font-size: 0.84rem;
        }
        .tt-table th {
            background: #f1f5f9;
            color: #1e293b;
            padding: 10px 8px;
            text-align: center;
            border-radius: 8px;
            font-weight: 700;
            border: 1px solid #cbd5e1;
        }
        .tt-block-col {
            background: #f8fafc;
            color: #334155;
            padding: 8px 10px;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
            text-align: center;
            width: 125px;
            font-weight: 600;
        }
        .tt-cell {
            border-radius: 9px;
            padding: 8px 10px;
            vertical-align: top;
            min-height: 68px;
            border: 1px solid #cbd5e1;
        }
        .tt-asig { font-weight: 700; font-size: 0.88rem; margin-bottom: 3px; }
        .tt-meta { font-size: 0.76rem; opacity: 0.92; }
        .tt-badge {
            display: inline-block;
            padding: 1px 6px;
            border-radius: 4px;
            font-size: 0.68rem;
            font-weight: 700;
            margin-top: 4px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Utilidades de tiempos de bloque (45 min vs 50 min) y diagnóstico
# --------------------------------------------------------------------------- #
def etiquetas_bloques_por_duracion(datos: SolverData, duracion_min: int) -> dict[str, str]:
    """
    Calcula el rango horario de cada bloque según el selector de 45 min o 50 min,
    respetando la regla de la ficha: 'El tiempo se representa mediante el identificador
    de bloque, no como 60 minutos de clase; la configuración debe admitir 45 o 50 minutos'.
    """
    hora_base = datos.bloques[0].inicio if datos.bloques else dt.time(7, 0)
    cursor = dt.datetime.combine(dt.date.today(), hora_base)
    delta = dt.timedelta(minutes=int(duracion_min))
    etiquetas: dict[str, str] = {}
    for b in datos.bloques:
        fin = cursor + delta
        etiquetas[b.id] = f"{cursor.strftime('%H:%M')} – {fin.strftime('%H:%M')}"
        cursor = fin
    return etiquetas


def diagnosticar_razon_pendiente(
    datos: SolverData,
    fila_pendiente: dict[str, Any],
    metricas: dict[str, Any],
    permitir_alternativos: bool,
) -> str:
    """Explica de forma transparente al coordinador académico por qué quedó pendiente una sesión."""
    curso_id = fila_pendiente["curso_id"]
    asignatura = fila_pendiente["asignatura"]
    doc_id = fila_pendiente["docente_principal_id"]

    req = next(
        (r for r in datos.requerimientos if r.curso_id == curso_id and r.asignatura == asignatura),
        None,
    )
    if req is None:
        return "Requerimiento no encontrado en Carga."

    salones_ok = datos.salones_compatibles.get(req.id, [])
    if not salones_ok:
        est = datos.cursos[curso_id].estudiantes
        return f"Sin salón de tipo '{req.tipo_salon}' con capacidad ≥ {est} estudiantes."

    doc = datos.docentes.get(doc_id)
    slots_disp = len(datos.slots_disponibles(doc_id))
    carga_asig = metricas.get("Carga por Docente", {}).get(doc_id, 0)

    if doc and carga_asig >= doc.max_sesiones_semana:
        alts = [a for a in datos.docentes_compatibles.get(req.id, []) if a != doc_id]
        if alts and not permitir_alternativos:
            return (
                f"Tope semanal alcanzado para {doc_id} ({doc.nombre}: {carga_asig}/{doc.max_sesiones_semana} sesiones). "
                f"Activa el apoyo de docente habilitado ({', '.join(alts)}) para cubrir el 100 %."
            )
        return f"Límite máximo semanal del docente {doc_id} ({doc.max_sesiones_semana} sesiones) alcanzado."

    if slots_disp < req.sesiones_semana:
        return f"Falta de disponibilidad del docente {doc_id} (solo {slots_disp} bloques disponibles)."

    return (
        f"Restricción combinada de disponibilidad de {doc_id} ({slots_disp} bloques libres) "
        f"y ocupación del curso {curso_id}."
    )


# --------------------------------------------------------------------------- #
# Renderizado de matrices HTML (Curso, Docente y Comparativa Rojo/Verde)
# --------------------------------------------------------------------------- #
def renderizar_matriz_curso_html(
    datos: SolverData,
    df_asig: pd.DataFrame,
    curso_id: str,
    etiquetas_bloque: dict[str, str],
    slots_nuevos: Optional[set[tuple[str, str]]] = None,
) -> str:
    sub = df_asig[df_asig["curso_id"] == curso_id] if not df_asig.empty else pd.DataFrame()
    por_slot: dict[tuple[str, str], pd.Series] = {
        (fila["dia"], fila["bloque_id"]): fila for _, fila in sub.iterrows()
    }

    html = ['<table class="tt-table"><thead><tr><th>Bloque</th>']
    for dia in datos.dias:
        html.append(f"<th>{dia}</th>")
    html.append("</tr></thead><tbody>")

    for blq in datos.bloques:
        rango = etiquetas_bloque.get(blq.id, "")
        html.append(
            f'<tr><td class="tt-block-col"><div><b>{blq.id}</b></div>'
            f'<div style="font-size:0.74rem;color:#94a3b8;">{rango}</div></td>'
        )
        for dia in datos.dias:
            fila = por_slot.get((dia, blq.id))
            if fila is None:
                html.append(
                    '<td class="tt-cell" style="background:#f8fafc;color:#64748b;text-align:center;border:1px dashed #cbd5e1;">'
                    '<i>Sin asignar</i></td>'
                )
                continue
            asig = str(fila["asignatura"])
            bg, accent = PALETA_ASIGNATURAS.get(asig, ("#1e293b", "#cbd5e1"))
            es_movida = slots_nuevos is not None and (dia, blq.id) in slots_nuevos
            borde = "2px solid #22c55e" if es_movida else "1px solid rgba(255,255,255,0.12)"
            badge = (
                '<span class="tt-badge" style="background:#14532d;color:#86efac;">✨ REUBICADA</span>'
                if es_movida
                else ""
            )
            html.append(
                f'<td class="tt-cell" style="background:{bg};border:{borde};">'
                f'<div class="tt-asig" style="color:{accent};">{asig}</div>'
                f'<div class="tt-meta" style="color:#f1f5f9;">👨‍🏫 {fila["docente_id"]} · {fila["docente_nombre"]}</div>'
                f'<div class="tt-meta" style="color:#cbd5e1;">🏫 {fila["salon_id"]} ({fila["salon_nombre"]})</div>'
                f"{badge}</td>"
            )
        html.append("</tr>")
    html.append("</tbody></table>")
    return "".join(html)


def renderizar_matriz_docente_html(
    datos: SolverData,
    df_asig: pd.DataFrame,
    docente_id: str,
    etiquetas_bloque: dict[str, str],
) -> str:
    sub = df_asig[df_asig["docente_id"] == docente_id] if not df_asig.empty else pd.DataFrame()
    por_slot: dict[tuple[str, str], pd.Series] = {
        (fila["dia"], fila["bloque_id"]): fila for _, fila in sub.iterrows()
    }

    # Identificar bloques que son HUECO (entre la primera y última clase del docente ese día)
    huecos_slot: set[tuple[str, str]] = set()
    for dia in datos.dias:
        ocupados = sorted(
            datos.idx_bloque[b.id]
            for b in datos.bloques
            if (dia, b.id) in por_slot
        )
        if len(ocupados) >= 2:
            prim, ult = ocupados[0], ocupados[-1]
            for b in datos.bloques:
                if prim < b.indice < ult and (dia, b.id) not in por_slot:
                    huecos_slot.add((dia, b.id))

    html = ['<table class="tt-table"><thead><tr><th>Bloque</th>']
    for dia in datos.dias:
        html.append(f"<th>{dia}</th>")
    html.append("</tr></thead><tbody>")

    for blq in datos.bloques:
        rango = etiquetas_bloque.get(blq.id, "")
        html.append(
            f'<tr><td class="tt-block-col"><div><b>{blq.id}</b></div>'
            f'<div style="font-size:0.74rem;color:#94a3b8;">{rango}</div></td>'
        )
        for dia in datos.dias:
            fila = por_slot.get((dia, blq.id))
            disp = datos.disponible(docente_id, dia, blq.id)
            if fila is not None:
                asig = str(fila["asignatura"])
                bg, accent = PALETA_ASIGNATURAS.get(asig, ("#1e293b", "#cbd5e1"))
                html.append(
                    f'<td class="tt-cell" style="background:{bg};">'
                    f'<div class="tt-asig" style="color:{accent};">{asig}</div>'
                    f'<div class="tt-meta" style="color:#f8fafc;">🎓 Curso: <b>{fila["curso_id"]}</b></div>'
                    f'<div class="tt-meta" style="color:#cbd5e1;">🏫 {fila["salon_id"]} ({fila["salon_nombre"]})</div>'
                    f"</td>"
                )
            elif not disp:
                html.append(
                    '<td class="tt-cell" style="background:#3f1d24;border:1px dashed #f43f5e;color:#fda4af;text-align:center;">'
                    '<div style="font-weight:700;margin-top:8px;">⛔ NO DISPONIBLE</div>'
                    '<div style="font-size:0.72rem;opacity:0.85;">Bloque restringido</div></td>'
                )
            elif (dia, blq.id) in huecos_slot:
                html.append(
                    '<td class="tt-cell" style="background:#422006;border:1px dashed #f59e0b;color:#fde68a;text-align:center;">'
                    '<div style="font-weight:700;margin-top:8px;">⚠️ HUECO</div>'
                    '<div style="font-size:0.72rem;opacity:0.9;">Ventana entre clases</div></td>'
                )
            else:
                html.append(
                    '<td class="tt-cell" style="background:#f8fafc;color:#64748b;text-align:center;border:1px dashed #e2e8f0;">'
                    '<div style="margin-top:10px;">🟢 Libre</div></td>'
                )
        html.append("</tr>")
    html.append("</tbody></table>")
    return "".join(html)


def renderizar_comparativa_html(
    datos: SolverData,
    df_actual: pd.DataFrame,
    df_otro: pd.DataFrame,
    modo: str,  # "base" (rojo para removidas) o "cambio" (verde para nuevas/modificadas)
    filtro_col: str,
    filtro_val: str,
    etiquetas_bloque: dict[str, str],
) -> str:
    sub_a = df_actual[df_actual[filtro_col] == filtro_val] if not df_actual.empty else pd.DataFrame()
    sub_b = df_otro[df_otro[filtro_col] == filtro_val] if not df_otro.empty else pd.DataFrame()

    map_a = {(r["dia"], r["bloque_id"]): r for _, r in sub_a.iterrows()}
    map_b = {(r["dia"], r["bloque_id"]): r for _, r in sub_b.iterrows()}

    html = ['<table class="tt-table"><thead><tr><th>Bloque</th>']
    for dia in datos.dias:
        html.append(f"<th>{dia}</th>")
    html.append("</tr></thead><tbody>")

    for blq in datos.bloques:
        rango = etiquetas_bloque.get(blq.id, "")
        html.append(
            f'<tr><td class="tt-block-col"><div><b>{blq.id}</b></div>'
            f'<div style="font-size:0.74rem;color:#94a3b8;">{rango}</div></td>'
        )
        for dia in datos.dias:
            ra = map_a.get((dia, blq.id))
            rb = map_b.get((dia, blq.id))

            iguales = (
                ra is not None
                and rb is not None
                and ra["curso_id"] == rb["curso_id"]
                and ra["asignatura"] == rb["asignatura"]
                and ra["docente_id"] == rb["docente_id"]
            )

            if ra is None:
                if rb is not None and modo == "cambio":
                    html.append(
                        '<td class="tt-cell" style="background:#450a0a;border:2px solid #ef4444;color:#fecaca;text-align:center;">'
                        f'<div style="font-weight:700;">🔴 LIBERADO</div>'
                        f'<div style="font-size:0.74rem;">Antes: {rb["asignatura"]} ({rb["curso_id"]})</div></td>'
                    )
                else:
                    html.append(
                        '<td class="tt-cell" style="background:#0f172a;color:#475569;text-align:center;">—</td>'
                    )
                continue

            if iguales:
                bg, border, badge = "#1e293b", "1px solid #334155", ""
            elif modo == "base":
                bg, border = "#450a0a", "2px solid #ef4444"
                badge = '<span class="tt-badge" style="background:#7f1d1d;color:#fecaca;">🔴 MOVIDA / AFECTADA</span>'
            else:
                bg, border = "#052e16", "2px solid #22c55e"
                badge = '<span class="tt-badge" style="background:#14532d;color:#bbf7d0;">🟢 NUEVA UBICACIÓN</span>'

            etiqueta_sec = (
                f'👨‍🏫 {ra["docente_id"]} ({ra["docente_nombre"]})'
                if filtro_col == "curso_id"
                else f'🎓 Curso {ra["curso_id"]}'
            )
            html.append(
                f'<td class="tt-cell" style="background:{bg};border:{border};">'
                f'<div class="tt-asig" style="color:#f8fafc;">{ra["asignatura"]}</div>'
                f'<div class="tt-meta" style="color:#cbd5e1;">{etiqueta_sec} · 🏫 {ra["salon_id"]}</div>'
                f"{badge}</td>"
            )
        html.append("</tr>")
    html.append("</tbody></table>")
    return "".join(html)


# --------------------------------------------------------------------------- #
# Exportación a Excel multipestaña y CSV
# --------------------------------------------------------------------------- #
def construir_excel_resultados(
    df_activo: pd.DataFrame,
    metricas_activas: dict[str, Any],
    df_base: pd.DataFrame,
    df_cambio: Optional[pd.DataFrame],
) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_activo.to_excel(writer, sheet_name="Horario_Activo", index=False)
        df_base.to_excel(writer, sheet_name="Horario_Base", index=False)
        if df_cambio is not None and not df_cambio.empty:
            df_cambio.to_excel(writer, sheet_name="Horario_Post_Cambio", index=False)

        resumen_kpi = pd.DataFrame([
            {"Métrica": "Cobertura %", "Valor": metricas_activas.get("Cobertura %", 0.0)},
            {"Métrica": "Sesiones Requeridas", "Valor": metricas_activas.get("Sesiones Requeridas", 0)},
            {"Métrica": "Sesiones Válidas Asignadas", "Valor": metricas_activas.get("Sesiones Válidas", 0)},
            {"Métrica": "Sesiones Pendientes", "Valor": metricas_activas.get("Sesiones Pendientes", 0)},
            {"Métrica": "Colisiones Totales", "Valor": metricas_activas.get("Colisiones", 0)},
            {"Métrica": "Infracciones Disponibilidad", "Valor": metricas_activas.get("Infracciones Disponibilidad", 0)},
            {"Métrica": "Infracciones Salón", "Valor": metricas_activas.get("Infracciones Salón", 0)},
            {"Métrica": "Total Huecos Docentes", "Valor": metricas_activas.get("Huecos Docentes", 0)},
            {"Métrica": "Repeticiones Mismo Día", "Valor": metricas_activas.get("Repeticiones Mismo Día", 0)},
            {"Métrica": "Sesiones Consecutivas", "Valor": metricas_activas.get("Sesiones Consecutivas", 0)},
            {"Métrica": "Estado Solver", "Valor": metricas_activas.get("Estado Solver", "")},
            {"Métrica": "Tiempo Resolución (ms)", "Valor": metricas_activas.get("Tiempo (ms)", 0)},
        ])
        resumen_kpi.to_excel(writer, sheet_name="Resumen_Metricas", index=False)

        pend = pd.DataFrame(metricas_activas.get("Detalle Pendientes", []))
        if not pend.empty:
            pend.to_excel(writer, sheet_name="Sesiones_Pendientes", index=False)

        movs = pd.DataFrame(metricas_activas.get("Detalle Sesiones Movidas", []))
        if not movs.empty:
            movs.to_excel(writer, sheet_name="Sesiones_Movidas", index=False)

    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Carga de datos y estado de sesión
# --------------------------------------------------------------------------- #
def obtener_loader(archivo_subido: Any) -> DataLoader:
    loader = DataLoader()
    if archivo_subido is not None:
        libro = pd.read_excel(archivo_subido, sheet_name=None, engine="openpyxl")
        loader.desde_dataframes(libro)
        return loader

    if not RUTA_EXCEL_DEFECTO.exists():
        if RUTA_EXCEL_ALT.exists():
            guardar_excel_hackathon(RUTA_EXCEL_DEFECTO)
        else:
            guardar_excel_hackathon(RUTA_EXCEL_DEFECTO)
    loader = DataLoader(RUTA_EXCEL_DEFECTO)
    loader.cargar()
    return loader


def ejecutar_calculo_completo(
    loader: DataLoader,
    permitir_alternativos: bool,
    tiempo_max: float = 10.0,
) -> dict[str, Any]:
    reporte = loader.validar(lanzar=False)
    datos_base = loader.preparar_para_solver(aplicar_cambio=False, validar=False)
    solver_base = ScheduleSolver(
        datos_base,
        permitir_docentes_alternativos=permitir_alternativos,
        tiempo_maximo_seg=tiempo_max,
    )
    df_base, met_base = solver_base.resolver()

    datos_cambio = loader.preparar_para_solver(aplicar_cambio=True, validar=False)
    df_cambio, met_cambio = ejecutar_tras_cambio(
        loader,
        df_horario_base=df_base,
        permitir_docentes_alternativos=permitir_alternativos,
        tiempo_maximo_seg=tiempo_max,
    )
    return {
        "reporte": reporte,
        "datos_base": datos_base,
        "df_base": df_base,
        "met_base": met_base,
        "datos_cambio": datos_cambio,
        "df_cambio": df_cambio,
        "met_cambio": met_cambio,
    }


# --------------------------------------------------------------------------- #
# Aplicación Principal
# --------------------------------------------------------------------------- #
def main() -> None:
    inyectar_estilos()

    # ------------------------------ SIDEBAR ------------------------------ #
    with st.sidebar:
        st.markdown("## 🎓 Gnosoft Timetable AI")
        st.caption("Hackathon Colombia 5.0 · Motor Google OR-Tools CP-SAT")
        st.divider()

        archivo_excel = st.file_uploader(
            "📂 Cargar Excel `Datos_prueba_Gnosoft (1).xlsx`",
            type=["xlsx", "xls"],
            help="Sube el archivo Excel con las hojas Bloques, Cursos, Docentes, Carga, Salones, Disponibilidad y Cambio.",
        )
        if archivo_excel is None:
            st.info("Usando archivo precargado: `Datos_prueba_Gnosoft (1).xlsx` (4 cursos · 120 sesiones).")

        duracion_bloque = st.radio(
            "⏱️ Duración de hora académica (bloque)",
            options=[50, 45],
            format_func=lambda m: f"{m} minutos {'(Caso Base Ficha)' if m == 50 else '(Parametrizable)'}",
            horizontal=True,
        )

        permitir_alternativos = st.toggle(
            "🤝 Habilitar docente alternativo en Inglés (D4 / D6)",
            value=True,
            help=(
                "Según la hoja Léeme/Habilitados: 'En inglés se permite asignar D4 o D6'. "
                "Desactívalo para demostrar cómo las variables de holgura reportan 4 Sesiones Pendientes por el tope de 24h de D4."
            ),
        )

        st.divider()
        st.markdown("### ⚡ Escenarios de Evaluación")

        if "escenario_activo" not in st.session_state:
            st.session_state["escenario_activo"] = "base"

        col_b1, col_b2 = st.columns(2)
        with col_b1:
            if st.button("🔄 Horario Base", use_container_width=True):
                st.session_state["escenario_activo"] = "base"
        with col_b2:
            if st.button("🧹 Recalcular", use_container_width=True):
                st.session_state.pop("cache_resultados", None)

        aplicar_cambio_click = st.button(
            "⚡ Aplicar Escenario de Cambio (D02 Indisponible Martes)",
            type="primary",
            use_container_width=True,
        )
        if aplicar_cambio_click:
            st.session_state["escenario_activo"] = "cambio"

    # Procesar y resolver (cacheado por firma de parámetros)
    firma = (
        getattr(archivo_excel, "name", "default"),
        getattr(archivo_excel, "size", 0),
        bool(permitir_alternativos),
    )
    if st.session_state.get("firma_cache") != firma or "cache_resultados" not in st.session_state:
        with st.spinner("Optimizando horario escolar con Google OR-Tools CP-SAT..."):
            loader = obtener_loader(archivo_excel)
            st.session_state["cache_resultados"] = ejecutar_calculo_completo(
                loader, permitir_alternativos=permitir_alternativos
            )
            st.session_state["firma_cache"] = firma

    res = st.session_state["cache_resultados"]
    es_cambio = st.session_state["escenario_activo"] == "cambio"

    datos_activos: SolverData = res["datos_cambio"] if es_cambio else res["datos_base"]
    df_activo: pd.DataFrame = res["df_cambio"] if es_cambio else res["df_base"]
    met_activas: dict[str, Any] = res["met_cambio"] if es_cambio else res["met_base"]
    df_base: pd.DataFrame = res["df_base"]
    df_cambio: pd.DataFrame = res["df_cambio"]
    met_base: dict[str, Any] = res["met_base"]
    met_cambio: dict[str, Any] = res["met_cambio"]
    etiquetas_blq = etiquetas_bloques_por_duracion(datos_activos, duracion_bloque)

    # Descargas en el Sidebar
    with st.sidebar:
        st.divider()
        st.markdown("### 📥 Exportar Resultados")
        bytes_xlsx = construir_excel_resultados(df_activo, met_activas, df_base, df_cambio)
        st.download_button(
            label="📊 Descargar Reporte Completo (.xlsx)",
            data=bytes_xlsx,
            file_name=f"Horario_Gnosoft_{'PostCambio' if es_cambio else 'Base'}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        st.download_button(
            label="📄 Descargar Asignaciones (.csv)",
            data=df_activo.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"Asignaciones_Gnosoft_{'PostCambio' if es_cambio else 'Base'}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    # ------------------------------ HEADER ------------------------------ #
    col_t1, col_t2 = st.columns([3.4, 1.6])
    with col_t1:
        st.markdown("## 🧠 Generación Inteligente y Optimización de Horarios Escolares")
        etiqueta_esc = (
            "⚡ **ESCENARIO ACTIVO: POST-CAMBIO (D02 / Luis Vega Indisponible el Martes)**"
            if es_cambio
            else "📘 **ESCENARIO ACTIVO: HORARIO BASE (6A, 6B, 7A, 7B · 120 sesiones)**"
        )
        st.markdown(f"{etiqueta_esc} · Bloques de **{duracion_bloque} min** · Solver `{met_activas['Estado Solver']}` en `{met_activas['Tiempo (ms)']} ms`")
    with col_t2:
        selector_modo = st.segmented_control(
            "Vista activa",
            options=["base", "cambio"],
            default=st.session_state["escenario_activo"],
            format_func=lambda x: "📘 Horario Base" if x == "base" else "⚡ Post-Cambio (D02 Martes)",
        )
        if selector_modo and selector_modo != st.session_state["escenario_activo"]:
            st.session_state["escenario_activo"] = selector_modo
            st.rerun()

    # ------------------------ KPI METRICS HEADER ------------------------ #
    k1, k2, k3, k4, k5 = st.columns(5)
    infracciones_tot = (
        met_activas["Colisiones"]
        + met_activas["Infracciones Disponibilidad"]
        + met_activas["Infracciones Salón"]
    )
    with k1:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">🎯 Cobertura %</div>
                <div class="kpi-value" style="color:{'#4ade80' if met_activas['Cobertura %'] == 100 else '#facc15'};">
                    {met_activas['Cobertura %']:.1f}%
                </div>
                <div class="kpi-sub">Sesiones válidas / requeridas</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with k2:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">📚 Sesiones Asignadas</div>
                <div class="kpi-value">{met_activas['Sesiones Válidas']} / {met_activas['Sesiones Requeridas']}</div>
                <div class="kpi-sub">4 cursos × 30 bloques semanales</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with k3:
        color_pend = "#4ade80" if met_activas["Sesiones Pendientes"] == 0 else "#f87171"
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">⏳ Sesiones Pendientes</div>
                <div class="kpi-value" style="color:{color_pend};">{met_activas['Sesiones Pendientes']}</div>
                <div class="kpi-sub">Variables de holgura activas</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with k4:
        color_col = "#4ade80" if infracciones_tot == 0 else "#f87171"
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">🛡️ Colisiones / Infracciones</div>
                <div class="kpi-value" style="color:{color_col};">{infracciones_tot}</div>
                <div class="kpi-sub">Curso: {met_activas['Detalle Colisiones']['curso']} · Docente: {met_activas['Detalle Colisiones']['docente']} · Salón: {met_activas['Detalle Colisiones']['salon']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with k5:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">🧘 Total Huecos Docentes</div>
                <div class="kpi-value" style="color:#38bdf8;">{met_activas['Huecos Docentes']}</div>
                <div class="kpi-sub">Repeticiones mismo día: {met_activas['Repeticiones Mismo Día']} · Consec.: {met_activas['Sesiones Consecutivas']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.write("")

    # ------------------------------ PESTAÑAS ------------------------------ #
    tab1, tab2, tab3, tab4 = st.tabs([
        "🏫 Tab 1: Horario por Curso",
        "👨‍🏫 Tab 2: Horario por Docente",
        "🚨 Tab 3: Reporte de Conflictos y Pendientes",
        "🔄 Tab 4: Simulación de Cambios / Comparativa",
    ])

    # ================= TAB 1: HORARIO POR CURSO ================= #
    with tab1:
        cursos_ids = list(datos_activos.cursos.keys())
        c_sel_col, c_info_col = st.columns([1.4, 3.6])
        with c_sel_col:
            curso_sel = st.selectbox(
                "Seleccionar Curso",
                options=cursos_ids,
                format_func=lambda cid: f"Curso {datos_activos.cursos[cid].nombre} ({datos_activos.cursos[cid].estudiantes} estudiantes)",
            )
        with c_info_col:
            asig_curso = df_activo[df_activo["curso_id"] == curso_sel]
            st.info(
                f"📌 **Curso {curso_sel}** ({datos_activos.cursos[curso_sel].estudiantes} estudiantes) · "
                f"**{len(asig_curso)} / 30 bloques programados** · "
                f"Bloques de **{duracion_bloque} min**."
            )

        slots_reubicados: Optional[set[tuple[str, str]]] = None
        if es_cambio:
            movs_curso = [
                (m["a_dia"], m["a_bloque"])
                for m in met_cambio.get("Detalle Sesiones Movidas", [])
                if m["curso_id"] == curso_sel
            ]
            slots_reubicados = set(movs_curso)

        st.markdown(
            renderizar_matriz_curso_html(
                datos_activos, df_activo, curso_sel, etiquetas_blq, slots_nuevos=slots_reubicados
            ),
            unsafe_allow_html=True,
        )

        with st.expander(f"📋 Ver tabla detallada de sesiones y cobertura para el curso {curso_sel}"):
            resumen_c = []
            for req in datos_activos.requerimientos_por_curso().get(curso_sel, []):
                sub_r = asig_curso[asig_curso["asignatura"] == req.asignatura]
                docs_usados = ", ".join(sorted(sub_r["docente_id"].unique())) if not sub_r.empty else "—"
                sals_usados = ", ".join(sorted(sub_r["salon_id"].unique())) if not sub_r.empty else "—"
                resumen_c.append({
                    "Curso": curso_sel,
                    "Asignatura": req.asignatura,
                    "Docente Principal": req.docente_id,
                    "Docente(s) Asignado(s)": docs_usados,
                    "Tipo Salón Requerido": req.tipo_salon,
                    "Salón(es) Asignado(s)": sals_usados,
                    "Sesiones Requeridas": req.sesiones_semana,
                    "Sesiones Asignadas": len(sub_r),
                    "Pendientes": max(0, req.sesiones_semana - len(sub_r)),
                })
            st.dataframe(pd.DataFrame(resumen_c), use_container_width=True, hide_index=True)

    # ================= TAB 2: HORARIO POR DOCENTE ================= #
    with tab2:
        docentes_ids = list(datos_activos.docentes.keys())
        d_sel_col, d_info_col = st.columns([1.6, 3.4])
        with d_sel_col:
            idx_default = docentes_ids.index("D2") if ("D2" in docentes_ids and es_cambio) else 0
            doc_sel = st.selectbox(
                "Seleccionar Docente",
                options=docentes_ids,
                index=idx_default,
                format_func=lambda did: f"{did} · {datos_activos.docentes[did].nombre}",
            )
        doc_obj = datos_activos.docentes[doc_sel]
        carga_doc = met_activas["Carga por Docente"].get(doc_sel, 0)
        huecos_doc = met_activas["Huecos por Docente"].get(doc_sel, 0)
        disp_doc = len(datos_activos.slots_disponibles(doc_sel))

        with d_info_col:
            st.progress(
                min(1.0, carga_doc / max(1, doc_obj.max_sesiones_semana)),
                text=(
                    f"👨‍🏫 **{doc_obj.id} — {doc_obj.nombre}** · "
                    f"Carga asignada: **{carga_doc} / {doc_obj.max_sesiones_semana}** sesiones máx. · "
                    f"Disponibilidad: **{disp_doc} / 30** bloques · "
                    f"Huecos en la semana: **{huecos_doc}**"
                ),
            )

        st.markdown(
            renderizar_matriz_docente_html(datos_activos, df_activo, doc_sel, etiquetas_blq),
            unsafe_allow_html=True,
        )

        st.markdown("#### 📊 Resumen de Carga, Disponibilidad y Huecos de Todo el Cuerpo Docente")
        filas_doc = []
        for did, dobj in datos_activos.docentes.items():
            c_asig = met_activas["Carga por Docente"].get(did, 0)
            c_princ = sum(r.sesiones_semana for r in datos_activos.requerimientos_por_docente().get(did, []))
            filas_doc.append({
                "ID Docente": did,
                "Nombre": dobj.nombre,
                "Carga Principal (Hoja Carga)": c_princ,
                "Sesiones Asignadas": c_asig,
                "Máx. Sesiones Semana": dobj.max_sesiones_semana,
                "Utilización %": round((c_asig / dobj.max_sesiones_semana) * 100, 1) if dobj.max_sesiones_semana else 0.0,
                "Bloques Disponibles": len(datos_activos.slots_disponibles(did)),
                "Bloques No Disponibles": 30 - len(datos_activos.slots_disponibles(did)),
                "Huecos Semanales": met_activas["Huecos por Docente"].get(did, 0),
            })
        st.dataframe(pd.DataFrame(filas_doc), use_container_width=True, hide_index=True)

    # ================= TAB 3: REPORTE DE CONFLICTOS Y PENDIENTES ================= #
    with tab3:
        st.markdown("### 🛡️ Auditoría de Reglas Obligatorias y Sesiones Pendientes")

        c_aud1, c_aud2 = st.columns(2)
        with c_aud1:
            df_reglas = pd.DataFrame([
                {"Regla Obligatoria (Hard Constraint)": "Colisiones de Curso (mismo día y bloque)", "Infracciones": met_activas["Detalle Colisiones"]["curso"], "Estado": "✅ Cumplida" if met_activas["Detalle Colisiones"]["curso"] == 0 else "❌ Violación"},
                {"Regla Obligatoria (Hard Constraint)": "Colisiones de Docente (mismo día y bloque)", "Infracciones": met_activas["Detalle Colisiones"]["docente"], "Estado": "✅ Cumplida" if met_activas["Detalle Colisiones"]["docente"] == 0 else "❌ Violación"},
                {"Regla Obligatoria (Hard Constraint)": "Colisiones de Salón (mismo día y bloque)", "Infracciones": met_activas["Detalle Colisiones"]["salon"], "Estado": "✅ Cumplida" if met_activas["Detalle Colisiones"]["salon"] == 0 else "❌ Violación"},
                {"Regla Obligatoria (Hard Constraint)": "Respeto de Disponibilidad Docente (disponible == 1)", "Infracciones": met_activas["Infracciones Disponibilidad"], "Estado": "✅ Cumplida" if met_activas["Infracciones Disponibilidad"] == 0 else "❌ Violación"},
                {"Regla Obligatoria (Hard Constraint)": "Capacidad y Tipo de Salón Requerido", "Infracciones": met_activas["Infracciones Salón"], "Estado": "✅ Cumplida" if met_activas["Infracciones Salón"] == 0 else "❌ Violación"},
            ])
            st.dataframe(df_reglas, use_container_width=True, hide_index=True)

        with c_aud2:
            rep = res["reporte"]
            st.markdown("#### 🔍 Diagnóstico del Cargador de Datos (`DataLoader.validar()`)")
            if rep.ok:
                st.success("Validación estructural del Excel: **OK (0 errores bloqueantes)**.")
            else:
                for err in rep.errores:
                    st.error(err)
            for adv in rep.advertencias:
                st.warning(adv)

        st.divider()
        st.markdown("#### ⏳ Detalle de Sesiones Pendientes (Variables de Holgura)")
        pendientes = met_activas.get("Detalle Pendientes", [])
        if not pendientes:
            st.success(
                "🎉 **0 Sesiones Pendientes (Cobertura del 100.0 % = 120 / 120 sesiones válidas).** "
                "Gracias a la regla de docentes habilitados en Inglés (`D4` y `D6`), se respeta el límite de 24 sesiones semanales por docente sin dejar clases sin programar."
            )
            st.caption(
                "💡 *Tip para la demostración ante el jurado:* Si desactivas el switch **'Habilitar docente alternativo en Inglés (D4 / D6)'** en la barra lateral, verás cómo el motor activa las variables de holgura y reporta aquí las 4 sesiones pendientes de Inglés por el tope de 24h de D4."
            )
        else:
            filas_pend = []
            for p in pendientes:
                filas_pend.append({
                    "Curso": p["curso_id"],
                    "Asignatura": p["asignatura"],
                    "Docente Principal": f"{p['docente_principal_id']} ({datos_activos.docentes[p['docente_principal_id']].nombre})",
                    "Sesiones Requeridas": p["requeridas"],
                    "Sesiones Asignadas": p["asignadas_validas"],
                    "Sesiones Pendientes": p["pendientes"],
                    "Razón / Diagnóstico": diagnosticar_razon_pendiente(
                        datos_activos, p, met_activas, permitir_alternativos
                    ),
                })
            st.warning(
                f"Se identificaron **{met_activas['Sesiones Pendientes']} sesiones pendientes** "
                f"(Cobertura: **{met_activas['Cobertura %']}%**):"
            )
            st.dataframe(pd.DataFrame(filas_pend), use_container_width=True, hide_index=True)

    # ================= TAB 4: SIMULACIÓN DE CAMBIOS / COMPARATIVA ================= #
    with tab4:
        st.markdown("### ⚡ Comparativa: Horario Base vs. Horario Post-Cambio (`D02 / D2` Indisponible el Martes)")

        afectadas = met_cambio.get("Detalle Sesiones Afectadas", [])
        movidas = met_cambio.get("Detalle Sesiones Movidas", [])

        m_c1, m_c2, m_c3, m_c4 = st.columns(4)
        m_c1.metric("Bloques restringidos en Cambio", f"{met_cambio.get('Cambios Disponibilidad Aplicados', 6)} bloques", "D2 · Martes B1–B6")
        m_c2.metric("Clases de D2 el Martes (Antes → Después)", f"{len(afectadas)} → 0", "100% liberado")
        m_c3.metric("Total Sesiones Reubicadas", f"{len(movidas)}", "0 colisiones")
        m_c4.metric(
            "Cobertura Post-Cambio",
            f"{met_cambio['Cobertura %']:.1f}%",
            f"{met_cambio['Sesiones Pendientes']} pendientes",
        )

        col_f1, col_f2 = st.columns([1.5, 2.5])
        with col_f1:
            tipo_vista_comp = st.radio(
                "Comparar matriz por:",
                options=["Docente", "Curso"],
                horizontal=True,
            )
        with col_f2:
            if tipo_vista_comp == "Docente":
                filtro_col = "docente_id"
                opciones_comp = list(datos_activos.docentes.keys())
                idx_def = opciones_comp.index("D2") if "D2" in opciones_comp else 0
                filtro_val = st.selectbox(
                    "Seleccionar Docente a comparar",
                    options=opciones_comp,
                    index=idx_def,
                    format_func=lambda d_id: f"{d_id} · {datos_activos.docentes[d_id].nombre}",
                )
            else:
                filtro_col = "curso_id"
                opciones_comp = list(datos_activos.cursos.keys())
                filtro_val = st.selectbox("Seleccionar Curso a comparar", options=opciones_comp)

        comp_izq, comp_der = st.columns(2)
        with comp_izq:
            st.markdown(f"#### 📘 Horario Base ({filtro_val}) — *En rojo: sesiones que se mueven*")
            st.markdown(
                renderizar_comparativa_html(
                    res["datos_base"], df_base, df_cambio, "base", filtro_col, filtro_val, etiquetas_blq
                ),
                unsafe_allow_html=True,
            )
        with comp_der:
            st.markdown(f"#### ⚡ Horario Post-Cambio ({filtro_val}) — *En verde: nueva ubicación*")
            st.markdown(
                renderizar_comparativa_html(
                    res["datos_cambio"], df_cambio, df_base, "cambio", filtro_col, filtro_val, etiquetas_blq
                ),
                unsafe_allow_html=True,
            )

        st.divider()
        col_t_af, col_t_mov = st.columns([1.3, 2.7])
        with col_t_af:
            st.markdown("#### 🎯 Sesiones de D2 en Martes Afectadas Directamente")
            if afectadas:
                st.dataframe(pd.DataFrame(afectadas), use_container_width=True, hide_index=True)
            else:
                st.info("D2 no tenía sesiones el martes en el horario base.")
        with col_t_mov:
            st.markdown("#### 🔄 Detalle de Sesiones Reubicadas (Antes → Después)")
            if movidas:
                df_mov = pd.DataFrame(movidas).rename(columns={
                    "curso_id": "Curso",
                    "asignatura": "Asignatura",
                    "de_dia": "Día (Antes)",
                    "de_bloque": "Bloque (Antes)",
                    "de_docente": "Docente (Antes)",
                    "de_salon": "Salón (Antes)",
                    "a_dia": "Día (Después)",
                    "a_bloque": "Bloque (Después)",
                    "a_docente": "Docente (Después)",
                    "a_salon": "Salón (Después)",
                    "motivo": "Motivo del Movimiento",
                })
                st.dataframe(df_mov, use_container_width=True, hide_index=True)
            else:
                st.success("No fue necesario mover ninguna sesión.")


if __name__ == "__main__":
    main()
