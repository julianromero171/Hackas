"""
Pruebas integrales de `ScheduleSolver` con los datos oficiales de la Hackathon Colombia 5.0 | Gnosoft.
"""
from __future__ import annotations

from pathlib import Path

from backend.data_loader import DataLoader
from backend.hackathon_dataset import construir_libro_hackathon, guardar_excel_hackathon
from backend.schedule_solver import ScheduleSolver, ejecutar_tras_cambio


def test_escenario_base_cobertura_100(tmp_path: Path) -> None:
    ruta = guardar_excel_hackathon(tmp_path / "hackathon_gnosoft.xlsx")
    loader = DataLoader(ruta)
    loader.cargar()
    rep = loader.validar()
    assert rep.ok, str(rep)

    datos_base = loader.preparar_para_solver(aplicar_cambio=False)
    solver = ScheduleSolver(datos_base, tiempo_maximo_seg=10.0)
    df_horario, metricas = solver.resolver()

    assert len(df_horario) == 120
    assert metricas["Cobertura %"] == 100.0
    assert metricas["Colisiones"] == 0
    assert metricas["Sesiones Pendientes"] == 0
    assert metricas["Infracciones Disponibilidad"] == 0
    assert metricas["Infracciones Salón"] == 0
    assert metricas["Repeticiones Mismo Día"] == 0
    assert metricas["Sesiones Consecutivas"] == 0
    # D1 no puede tener clase el viernes en B6
    d1_vie_b6 = df_horario[
        (df_horario["docente_id"] == "D1")
        & (df_horario["dia"] == "Viernes")
        & (df_horario["bloque_id"] == "B6")
    ]
    assert d1_vie_b6.empty
    # Ningún docente supera 24 sesiones semanales
    for doc_id, carga in metricas["Carga por Docente"].items():
        assert carga <= 24, f"{doc_id} tiene {carga} sesiones (> 24)"


def test_variables_holgura_sin_alternativos() -> None:
    """
    Si se deshabilitan los docentes alternativos (D6 en Inglés), D4 tiene 28 sesiones asignadas
    pero su límite es 24. El solver usa las variables de holgura (`pendiente`) y reporta
    exactamente 4 Sesiones Pendientes (116/120 = 96.67 % de cobertura) con 0 colisiones.
    """
    loader = DataLoader()
    loader.desde_dataframes(construir_libro_hackathon())
    datos_base = loader.preparar_para_solver(aplicar_cambio=False, validar=False)

    solver = ScheduleSolver(
        datos_base,
        permitir_docentes_alternativos=False,
        tiempo_maximo_seg=10.0,
    )
    df_horario, metricas = solver.resolver()

    assert len(df_horario) == 116
    assert metricas["Sesiones Pendientes"] == 4
    assert metricas["Cobertura %"] == 96.67
    assert metricas["Colisiones"] == 0


def test_ejecutar_tras_cambio_d2_martes() -> None:
    """
    Al aplicar la hoja Cambio (D2/D02 no disponible el martes), el solver reubica
    todas las sesiones de D2 del martes manteniendo 100 % de cobertura y 0 colisiones.
    """
    libro = construir_libro_hackathon()
    # Incluso si la hoja Cambio usa 'D02' (con cero), DataLoader lo reconcilia con 'D2'
    libro["Cambio"]["docente_id"] = "D02"

    loader = DataLoader()
    loader.desde_dataframes(libro)

    datos_base = loader.preparar_para_solver(aplicar_cambio=False)
    df_base, met_base = ScheduleSolver(datos_base, tiempo_maximo_seg=10.0).resolver()
    assert met_base["Cobertura %"] == 100.0

    df_cambio, met_cambio = ejecutar_tras_cambio(
        loader,
        df_horario_base=df_base,
        tiempo_maximo_seg=10.0,
    )

    assert len(df_cambio) == 120
    assert met_cambio["Cobertura %"] == 100.0
    assert met_cambio["Colisiones"] == 0
    assert met_cambio["Sesiones Pendientes"] == 0
    # D2 tiene 0 sesiones el martes en el nuevo horario
    d2_martes = df_cambio[(df_cambio["docente_id"] == "D2") & (df_cambio["dia"] == "Martes")]
    assert d2_martes.empty
    assert "Sesiones Afectadas por Cambio" in met_cambio
    assert "Sesiones Movidas" in met_cambio
