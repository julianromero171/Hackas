"""
Capa de carga y preparación de datos (Excel → estructuras limpias para OR-Tools).

Hojas soportadas en el libro Excel de la Hackathon Gnosoft:
    Leeme           : Concepto, Descripción                          (opcional)
    Bloques         : bloque_id, inicio, fin
    Cursos          : curso_id, nombre, estudiantes
    Docentes        : docente_id, nombre, max_sesiones_semana
    Habilitados     : asignatura, docente_id, habilitado             (opcional)
    Carga           : curso_id, asignatura, docente_principal_id, sesiones_semana, tipo_salon_requerido
    Salones         : salon_id, nombre, tipo, capacidad
    Disponibilidad  : docente_id, dia, bloque_id, disponible
    Cambio          : docente_id, dia, bloque_id, disponible_nuevo, motivo   (opcional)

Uso típico:
    loader = DataLoader("data/hackathon_gnosoft.xlsx")
    loader.cargar()
    reporte = loader.validar()
    datos_base = loader.preparar_para_solver(aplicar_cambio=False)
    datos_cambio = loader.preparar_para_solver(aplicar_cambio=True)
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Iterable, Optional, Union

import pandas as pd

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Constantes de esquema
# --------------------------------------------------------------------------- #
ESQUEMA: Final[dict[str, list[str]]] = {
    "Leeme": ["concepto", "descripcion"],
    "Bloques": ["bloque_id", "inicio", "fin"],
    "Cursos": ["curso_id", "nombre", "estudiantes"],
    "Docentes": ["docente_id", "nombre", "max_sesiones_semana"],
    "Habilitados": ["asignatura", "docente_id", "habilitado"],
    "Carga": ["curso_id", "asignatura", "docente_principal_id", "sesiones_semana", "tipo_salon_requerido"],
    "Salones": ["salon_id", "nombre", "tipo", "capacidad"],
    "Disponibilidad": ["docente_id", "dia", "bloque_id", "disponible"],
    "Cambio": ["docente_id", "dia", "bloque_id", "disponible_nuevo", "motivo"],
}
HOJAS_OPCIONALES: Final[frozenset[str]] = frozenset({"Leeme", "Habilitados", "Cambio"})

# Columnas de identificadores por hoja (se normalizan a str y no admiten nulos).
COLUMNAS_ID: Final[dict[str, list[str]]] = {
    "Bloques": ["bloque_id"],
    "Cursos": ["curso_id"],
    "Docentes": ["docente_id"],
    "Habilitados": ["docente_id"],
    "Carga": ["curso_id", "docente_principal_id"],
    "Salones": ["salon_id"],
    "Disponibilidad": ["docente_id", "bloque_id"],
    "Cambio": ["docente_id", "bloque_id"],
}

DIAS_CANONICOS: Final[list[str]] = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

_VERDADEROS: Final[frozenset[str]] = frozenset({"1", "true", "verdadero", "si", "s", "yes", "y", "x", "disponible"})
_FALSOS: Final[frozenset[str]] = frozenset({"0", "false", "falso", "no", "n", "", "no disponible"})

RutaExcel = Union[str, Path]
ClaveDisp = tuple[str, str, str]  # (docente_id, dia, bloque_id)


# --------------------------------------------------------------------------- #
# Estructuras de salida
# --------------------------------------------------------------------------- #
class DataValidationError(Exception):
    """Se lanza cuando los datos tienen errores que impiden construir el modelo."""

    def __init__(self, errores: list[str]) -> None:
        self.errores = errores
        super().__init__("Datos inválidos:\n  - " + "\n  - ".join(errores))


@dataclass
class ReporteValidacion:
    """Resultado de la validación: los errores bloquean el solver; las advertencias no."""

    errores: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errores

    def __str__(self) -> str:
        lineas = [f"Validación: {'OK' if self.ok else 'CON ERRORES'} "
                  f"({len(self.errores)} errores, {len(self.advertencias)} advertencias)"]
        lineas += [f"  [ERROR] {e}" for e in self.errores]
        lineas += [f"  [AVISO] {a}" for a in self.advertencias]
        return "\n".join(lineas)


@dataclass(frozen=True)
class Bloque:
    id: str
    inicio: dt.time
    fin: dt.time
    indice: int  # posición en la jornada (0 = primer bloque)


@dataclass(frozen=True)
class Curso:
    id: str
    nombre: str
    estudiantes: int


@dataclass(frozen=True)
class Docente:
    id: str
    nombre: str
    max_sesiones_semana: int


@dataclass(frozen=True)
class Salon:
    id: str
    nombre: str
    tipo: str
    capacidad: int


@dataclass(frozen=True)
class Requerimiento:
    """Una fila de la hoja Carga: el curso debe recibir N sesiones de la asignatura."""

    id: int
    curso_id: str
    asignatura: str
    docente_id: str  # docente_principal_id
    sesiones_semana: int
    tipo_salon: str
    docentes_habilitados: tuple[str, ...] = ()


@dataclass
class SolverData:
    """
    Estructuras limpias, indexadas y listas para un modelo CP-SAT (ScheduleSolver).

    Variable de decisión:  X[c, a, d, s, dia, b] ∈ {0, 1}
    """

    dias: list[str]
    bloques: list[Bloque]
    cursos: dict[str, Curso]
    docentes: dict[str, Docente]
    salones: dict[str, Salon]
    requerimientos: list[Requerimiento]
    # disponibilidad[(docente_id, dia, bloque_id)] -> bool (rejilla completa)
    disponibilidad: dict[ClaveDisp, bool]
    # requerimiento.id -> salones válidos (tipo correcto y capacidad suficiente)
    salones_compatibles: dict[int, list[str]]
    # requerimiento.id -> docentes válidos (principal + alternativos habilitados)
    docentes_compatibles: dict[int, list[str]]
    # asignatura (normalizada) -> lista de docente_id habilitados
    habilitados_por_asignatura: dict[str, list[str]]
    # Índices enteros (útiles para arrays / nombres compactos de variables)
    idx_dia: dict[str, int]
    idx_bloque: dict[str, int]
    # Metadatos opcionales (hoja Léeme)
    metadatos: dict[str, str] = field(default_factory=dict)
    # Bitácora de cambios de disponibilidad aplicados
    cambios_aplicados: list[dict[str, Any]] = field(default_factory=list)

    @property
    def slots(self) -> list[tuple[str, str]]:
        """Todos los pares (dia, bloque_id) en orden cronológico."""
        return [(d, b.id) for d in self.dias for b in self.bloques]

    def disponible(self, docente_id: str, dia: str, bloque_id: str) -> bool:
        return self.disponibilidad.get((docente_id, dia, bloque_id), False)

    def slots_disponibles(self, docente_id: str) -> list[tuple[str, str]]:
        return [(d, b) for d, b in self.slots if self.disponible(docente_id, d, b)]

    def requerimientos_por_curso(self) -> dict[str, list[Requerimiento]]:
        out: dict[str, list[Requerimiento]] = {c: [] for c in self.cursos}
        for r in self.requerimientos:
            out[r.curso_id].append(r)
        return out

    def requerimientos_por_docente(self) -> dict[str, list[Requerimiento]]:
        """Requerimientos donde el docente es el principal."""
        out: dict[str, list[Requerimiento]] = {d: [] for d in self.docentes}
        for r in self.requerimientos:
            out[r.docente_id].append(r)
        return out


# --------------------------------------------------------------------------- #
# Funciones auxiliares de normalización
# --------------------------------------------------------------------------- #
def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _es_nulo(valor: Any) -> bool:
    try:
        return valor is None or bool(pd.isna(valor))
    except (TypeError, ValueError):
        return False


_MAPA_DIAS: Final[dict[str, str]] = {_sin_tildes(d).lower(): d for d in DIAS_CANONICOS}
_MAPA_DIAS.update({k[:3]: v for k, v in list(_MAPA_DIAS.items())})  # abreviaturas: lun, mar, mie...


def normalizar_dia(valor: Any) -> Optional[str]:
    """'martes', 'MARTES', 'Mar', 'miercoles' → nombre canónico ('Martes', 'Miércoles'); None si no es válido."""
    if _es_nulo(valor):
        return None
    return _MAPA_DIAS.get(_sin_tildes(str(valor)).strip().lower())


def normalizar_id(valor: Any) -> Optional[str]:
    """Convierte IDs a str limpio. Excel suele leer 1 como 1.0 → '1'."""
    if _es_nulo(valor):
        return None
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = str(valor).strip()
    return texto or None


def _clave_id_canonica(valor: Any) -> Optional[str]:
    """
    Clave canónica para reconciliar 'D02' con 'D2' o 'B01' con 'B1'.
    Quita ceros a la izquierda en la parte numérica: 'D02' -> 'D2'.
    """
    if _es_nulo(valor) or not str(valor).strip():
        return None
    texto = str(valor).strip()
    m = re.fullmatch(r"([A-Za-z]+?)0*(\d+)", texto)
    if m:
        return f"{m.group(1).upper()}{int(m.group(2))}"
    return texto.upper()


def normalizar_bool(valor: Any) -> Optional[bool]:
    """1/0, Sí/No, True/False, X → bool. None si el valor es irreconocible."""
    if isinstance(valor, bool):
        return valor
    if _es_nulo(valor):
        return None
    if isinstance(valor, (int, float)):
        return bool(valor) if valor in (0, 1) else None
    texto = _sin_tildes(str(valor)).strip().lower()
    if texto in _VERDADEROS:
        return True
    if texto in _FALSOS:
        return False
    return None


def normalizar_hora(valor: Any) -> Optional[dt.time]:
    """Acepta datetime.time, datetime, '07:00', '7:00:00' o fracción de día de Excel (0.2916)."""
    if _es_nulo(valor):
        return None
    if isinstance(valor, dt.datetime):
        return valor.time()
    if isinstance(valor, dt.time):
        return valor
    if isinstance(valor, (int, float)) and 0 <= valor < 1:
        minutos = round(float(valor) * 24 * 60)
        return dt.time(minutos // 60, minutos % 60)
    for formato in ("%H:%M", "%H:%M:%S", "%I:%M %p"):
        try:
            return dt.datetime.strptime(str(valor).strip(), formato).time()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
# DataLoader
# --------------------------------------------------------------------------- #
class DataLoader:
    """Lee, normaliza, valida y transforma el Excel de la Hackathon para el solver."""

    def __init__(self, ruta_excel: Optional[RutaExcel] = None, *, disponible_por_defecto: bool = False) -> None:
        """
        :param ruta_excel: ruta al .xlsx (puede omitirse y usar `desde_dataframes`).
        :param disponible_por_defecto: valor asumido para combinaciones docente/día/bloque
               que no aparecen en la hoja Disponibilidad (conservador: False).
        """
        self.ruta_excel: Optional[Path] = Path(ruta_excel) if ruta_excel else None
        self.disponible_por_defecto = disponible_por_defecto
        self.hojas: dict[str, pd.DataFrame] = {}
        self.reporte: ReporteValidacion = ReporteValidacion()
        self.cambios_aplicados: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ carga
    def cargar(self) -> dict[str, pd.DataFrame]:
        """Lee todas las hojas del Excel con pandas y las normaliza."""
        if self.ruta_excel is None:
            raise ValueError("No se indicó la ruta del archivo Excel.")
        if not self.ruta_excel.exists():
            raise FileNotFoundError(self.ruta_excel)
        libro: dict[str, pd.DataFrame] = pd.read_excel(self.ruta_excel, sheet_name=None, engine="openpyxl")
        return self.desde_dataframes(libro)

    def desde_dataframes(self, libro: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        """Permite inyectar DataFrames ya cargados (tests, API, Google Sheets…)."""
        # Búsqueda de hojas insensible a mayúsculas/tildes/espacios.
        por_clave = {_sin_tildes(str(n)).strip().lower(): df for n, df in libro.items()}
        self.hojas = {}
        for hoja, columnas in ESQUEMA.items():
            clave = _sin_tildes(hoja).lower()
            df = por_clave.get(clave)
            if df is None and hoja == "Habilitados":
                # Alias comunes para la tabla de docentes habilitados por asignatura
                for alias in ("habilitacion", "docentes_asignaturas", "asignaturas_docentes", "asignaturas"):
                    if alias in por_clave:
                        df = por_clave[alias]
                        break
            if df is None:
                if hoja in HOJAS_OPCIONALES:
                    df = pd.DataFrame(columns=columnas)
                else:
                    raise DataValidationError([f"Falta la hoja obligatoria '{hoja}'."])
            self.hojas[hoja] = self._normalizar_hoja(hoja, df.copy())

        self._reconciliar_ids_docentes_y_bloques()
        return self.hojas

    @staticmethod
    def _normalizar_hoja(hoja: str, df: pd.DataFrame) -> pd.DataFrame:
        """Limpia nombres de columnas, elimina filas vacías y normaliza IDs/días/booleanos (idempotente)."""
        df.columns = [_sin_tildes(str(c)).strip().lower().replace(" ", "_") for c in df.columns]
        df = df.dropna(how="all").reset_index(drop=True).astype(object)

        for col in COLUMNAS_ID.get(hoja, []):
            if col in df.columns:
                df[col] = df[col].map(normalizar_id)
        if "dia" in df.columns:
            if "dia_original" not in df.columns:
                df["dia_original"] = df["dia"]
            df["dia"] = df["dia"].map(normalizar_dia)
        for col in ("disponible", "disponible_nuevo", "habilitado"):
            if col in df.columns:
                if f"{col}_original" not in df.columns:
                    df[f"{col}_original"] = df[col]
                df[col] = df[col].map(normalizar_bool)
        for col in ("nombre", "asignatura", "tipo", "tipo_salon_requerido", "motivo", "concepto", "descripcion"):
            if col in df.columns:
                df[col] = df[col].map(lambda v: None if _es_nulo(v) else str(v).strip())
        return df

    def _reconciliar_ids_docentes_y_bloques(self) -> None:
        """
        Reconcilia automáticamente variantes como 'D02' vs 'D2' o 'B01' vs 'B1'
        usando como referencia las claves primarias de las hojas 'Docentes' y 'Bloques'.
        """
        if "Docentes" in self.hojas and "docente_id" in self.hojas["Docentes"].columns:
            mapa_doc = {
                _clave_id_canonica(d): d
                for d in self.hojas["Docentes"]["docente_id"].dropna().unique()
            }
            for hoja, col in (
                ("Carga", "docente_principal_id"),
                ("Habilitados", "docente_id"),
                ("Disponibilidad", "docente_id"),
                ("Cambio", "docente_id"),
            ):
                if hoja in self.hojas and col in self.hojas[hoja].columns:
                    self.hojas[hoja][col] = self.hojas[hoja][col].map(
                        lambda v: mapa_doc.get(_clave_id_canonica(v), v) if v is not None else None
                    )

        if "Bloques" in self.hojas and "bloque_id" in self.hojas["Bloques"].columns:
            mapa_blq = {
                _clave_id_canonica(b): b
                for b in self.hojas["Bloques"]["bloque_id"].dropna().unique()
            }
            for hoja in ("Disponibilidad", "Cambio"):
                if hoja in self.hojas and "bloque_id" in self.hojas[hoja].columns:
                    self.hojas[hoja]["bloque_id"] = self.hojas[hoja]["bloque_id"].map(
                        lambda v: mapa_blq.get(_clave_id_canonica(v), v) if v is not None else None
                    )

    # -------------------------------------------------------------- validación
    def validar(self, *, lanzar: bool = False) -> ReporteValidacion:
        """
        Ejecuta todas las reglas de validación:
          1. Columnas requeridas.       2. IDs nulos y duplicados.
          3. Tipos numéricos / horas.   4. Integridad referencial (FK).
          5. Compatibilidad curso ↔ salón (tipo y capacidad).
          6. Factibilidad de carga (docentes y cursos).
        """
        if not self.hojas:
            raise RuntimeError("Primero llama a cargar() o desde_dataframes().")
        rep = ReporteValidacion()

        if self._validar_columnas(rep):
            self._validar_ids(rep)
            tipos_ok = self._validar_tipos(rep)
            self._validar_referencias(rep)
            if tipos_ok:  # las reglas siguientes requieren números válidos
                self._validar_salones(rep)
                self._validar_factibilidad(rep)

        self.reporte = rep
        if lanzar and not rep.ok:
            raise DataValidationError(rep.errores)
        return rep

    def _validar_columnas(self, rep: ReporteValidacion) -> bool:
        ok = True
        for hoja, columnas in ESQUEMA.items():
            if hoja in HOJAS_OPCIONALES and self.hojas[hoja].empty:
                continue
            faltantes = [c for c in columnas if c not in self.hojas[hoja].columns]
            if hoja == "Cambio" and "motivo" in faltantes:  # 'motivo' es informativo
                self.hojas[hoja]["motivo"] = None
                faltantes.remove("motivo")
            if faltantes:
                rep.errores.append(f"[{hoja}] faltan columnas: {', '.join(faltantes)}")
                ok = False
        return ok

    def _validar_ids(self, rep: ReporteValidacion) -> None:
        for hoja, columnas in COLUMNAS_ID.items():
            df = self.hojas[hoja]
            if hoja in HOJAS_OPCIONALES and df.empty:
                continue
            for col in columnas:
                nulos = df.index[df[col].isna()].tolist()
                if nulos:
                    rep.errores.append(f"[{hoja}] '{col}' nulo en filas Excel {self._filas(nulos)}")
        # Claves primarias únicas
        for hoja, pk in (("Bloques", "bloque_id"), ("Cursos", "curso_id"),
                         ("Docentes", "docente_id"), ("Salones", "salon_id")):
            serie = self.hojas[hoja][pk].dropna()
            dup = sorted(set(serie[serie.duplicated()]))
            if dup:
                rep.errores.append(f"[{hoja}] IDs duplicados: {', '.join(dup)}")
        # Claves compuestas
        disp = self.hojas["Disponibilidad"].dropna(subset=["docente_id", "dia", "bloque_id"])
        n_dup = int(disp.duplicated(["docente_id", "dia", "bloque_id"]).sum())
        if n_dup:
            rep.advertencias.append(
                f"[Disponibilidad] {n_dup} filas duplicadas (docente, día, bloque); se usa la última.")
        carga = self.hojas["Carga"]
        dup_carga = carga[carga.duplicated(["curso_id", "asignatura"], keep=False)]
        if not dup_carga.empty:
            rep.advertencias.append(
                f"[Carga] asignaturas repetidas para el mismo curso en filas {self._filas(dup_carga.index)}")

    def _validar_tipos(self, rep: ReporteValidacion) -> bool:
        ok = True
        enteros = [("Cursos", "estudiantes", 1), ("Docentes", "max_sesiones_semana", 0),
                   ("Carga", "sesiones_semana", 1), ("Salones", "capacidad", 1)]
        for hoja, col, minimo in enteros:
            df = self.hojas[hoja]
            num = pd.to_numeric(df[col], errors="coerce")
            malos = df.index[num.isna() | (num % 1 != 0) | (num < minimo)].tolist()
            if malos:
                rep.errores.append(f"[{hoja}] '{col}' debe ser entero ≥ {minimo} (filas {self._filas(malos)})")
                ok = False
            else:
                df[col] = num.astype(int)

        # Horas de bloques
        bl = self.hojas["Bloques"]
        bl["inicio"] = bl["inicio"].map(normalizar_hora)
        bl["fin"] = bl["fin"].map(normalizar_hora)
        for i, fila in bl.iterrows():
            if fila["inicio"] is None or fila["fin"] is None:
                rep.errores.append(f"[Bloques] hora inválida en bloque '{fila['bloque_id']}' (fila {i + 2})")
                ok = False
            elif fila["fin"] <= fila["inicio"]:
                rep.errores.append(f"[Bloques] '{fila['bloque_id']}': fin ({fila['fin']}) ≤ inicio ({fila['inicio']})")
                ok = False
        validos = [r for _, r in bl.iterrows() if r["inicio"] is not None and r["fin"] is not None]
        validos.sort(key=lambda r: r["inicio"])
        for a, b in zip(validos, validos[1:]):
            if b["inicio"] < a["fin"]:
                rep.errores.append(f"[Bloques] '{a['bloque_id']}' y '{b['bloque_id']}' se solapan")

        # Días y booleanos
        for hoja, col_bool in (("Disponibilidad", "disponible"), ("Cambio", "disponible_nuevo")):
            df = self.hojas[hoja]
            if hoja in HOJAS_OPCIONALES and df.empty:
                continue
            dias_malos = df.index[df["dia"].isna()].tolist()
            if dias_malos:
                valores = sorted({str(v) for v in df.loc[dias_malos, "dia_original"]})
                rep.errores.append(f"[{hoja}] día no reconocido {valores} (filas {self._filas(dias_malos)})")
            bool_malos = df.index[df[col_bool].isna()].tolist()
            if bool_malos:
                rep.errores.append(
                    f"[{hoja}] '{col_bool}' debe ser 1/0, Sí/No o True/False (filas {self._filas(bool_malos)})")
        return ok

    def _validar_referencias(self, rep: ReporteValidacion) -> None:
        cursos = set(self.hojas["Cursos"]["curso_id"].dropna())
        docentes = set(self.hojas["Docentes"]["docente_id"].dropna())
        bloques = set(self.hojas["Bloques"]["bloque_id"].dropna())
        tipos = {t.lower() for t in self.hojas["Salones"]["tipo"].dropna()}

        def revisar(hoja: str, col: str, universo: set[str], destino: str, minus: bool = False) -> None:
            df = self.hojas[hoja]
            if hoja in HOJAS_OPCIONALES and df.empty:
                return
            serie = df[col].dropna()
            faltan = sorted({v for v in serie if (v.lower() if minus else v) not in universo})
            if faltan:
                rep.errores.append(f"[{hoja}] '{col}' sin correspondencia en {destino}: {', '.join(faltan)}")

        revisar("Carga", "curso_id", cursos, "Cursos")
        revisar("Carga", "docente_principal_id", docentes, "Docentes")
        revisar("Carga", "tipo_salon_requerido", tipos, "Salones.tipo", minus=True)
        revisar("Habilitados", "docente_id", docentes, "Docentes")
        for hoja in ("Disponibilidad", "Cambio"):
            revisar(hoja, "docente_id", docentes, "Docentes")
            revisar(hoja, "bloque_id", bloques, "Bloques")

        sin_carga = sorted(cursos - set(self.hojas["Carga"]["curso_id"].dropna()))
        if sin_carga:
            rep.advertencias.append(f"[Cursos] sin asignaturas en Carga: {', '.join(sin_carga)}")
        sin_disp = sorted(set(self.hojas["Carga"]["docente_principal_id"].dropna())
                          - set(self.hojas["Disponibilidad"]["docente_id"].dropna()))
        if sin_disp:
            asumido = "disponibles" if self.disponible_por_defecto else "NO disponibles"
            rep.advertencias.append(
                f"[Disponibilidad] docentes con carga pero sin filas (se asumen {asumido}): {', '.join(sin_disp)}")

    def _validar_salones(self, rep: ReporteValidacion) -> None:
        """Descalce curso ↔ salón: debe existir al menos un salón del tipo con capacidad suficiente."""
        cursos = self.hojas["Cursos"].dropna(subset=["curso_id"]).set_index("curso_id")
        salones = self.hojas["Salones"]
        tipo_salon = salones["tipo"].fillna("").str.lower()
        for i, fila in self.hojas["Carga"].iterrows():
            if fila["curso_id"] not in cursos.index or fila["tipo_salon_requerido"] is None:
                continue
            est = int(cursos.at[fila["curso_id"], "estudiantes"])
            del_tipo = salones[tipo_salon == fila["tipo_salon_requerido"].lower()]
            if del_tipo.empty:
                continue  # ya reportado como FK
            if not (del_tipo["capacidad"] >= est).any():
                rep.errores.append(
                    f"[Carga fila {i + 2}] {fila['curso_id']} ({est} est.) – '{fila['asignatura']}': ningún salón "
                    f"'{fila['tipo_salon_requerido']}' tiene capacidad suficiente "
                    f"(máx {int(del_tipo['capacidad'].max())})")

        # Demanda vs. oferta por tipo de salón (condición necesaria)
        n_slots = len(self._dias()) * len(self.hojas["Bloques"])
        carga = self.hojas["Carga"]
        demanda = carga.groupby(carga["tipo_salon_requerido"].fillna("").str.lower())["sesiones_semana"].sum()
        oferta = salones.groupby(tipo_salon).size() * n_slots
        for tipo, horas in demanda.items():
            if tipo in oferta and horas > oferta[tipo]:
                rep.errores.append(
                    f"[Salones] tipo '{tipo}': se requieren {horas} sesiones y solo hay {oferta[tipo]} slots")

    def _mapa_habilitados(self) -> dict[str, list[str]]:
        """Devuelve asignatura_normalizada -> lista de docente_id habilitados."""
        out: dict[str, list[str]] = {}
        df_hab = self.hojas.get("Habilitados")
        if df_hab is not None and not df_hab.empty:
            for _, fila in df_hab.iterrows():
                if fila.get("habilitado") is True and fila.get("asignatura") and fila.get("docente_id"):
                    clave = _sin_tildes(str(fila["asignatura"])).strip().lower()
                    lista = out.setdefault(clave, [])
                    if fila["docente_id"] not in lista:
                        lista.append(fila["docente_id"])
        return out

    def _validar_factibilidad(self, rep: ReporteValidacion) -> None:
        """Condiciones necesarias de factibilidad (no suficientes) antes de llamar al solver."""
        carga = self.hojas["Carga"]
        n_slots = len(self._dias()) * len(self.hojas["Bloques"])

        for curso, total in carga.groupby("curso_id")["sesiones_semana"].sum().items():
            if total > n_slots:
                rep.errores.append(f"[Carga] {curso}: {total} sesiones > {n_slots} slots semanales")

        docentes = self.hojas["Docentes"].dropna(subset=["docente_id"]).set_index("docente_id")
        disp = self._disponibilidad_efectiva()
        libres = disp[disp["disponible"]].groupby("docente_id").size()
        hab_map = self._mapa_habilitados()

        for doc, sub_df in carga.groupby("docente_principal_id"):
            if doc not in docentes.index:
                continue
            total = int(sub_df["sesiones_semana"].sum())
            maximo = int(docentes.at[doc, "max_sesiones_semana"])
            n_libres = int(libres.get(doc, 0))

            # Verificar si alguna asignatura de este docente tiene docentes alternativos habilitados
            alternativos: set[str] = set()
            for asig in sub_df["asignatura"].dropna().unique():
                clave = _sin_tildes(str(asig)).strip().lower()
                for alt in hab_map.get(clave, []):
                    if alt != doc and alt in docentes.index:
                        alternativos.add(alt)

            if total > maximo:
                if alternativos:
                    rep.advertencias.append(
                        f"[Docentes] {doc}: carga principal {total} > máximo semanal {maximo}; "
                        f"requiere apoyo de docente(s) habilitado(s): {', '.join(sorted(alternativos))}"
                    )
                else:
                    rep.errores.append(f"[Docentes] {doc}: carga {total} > máximo semanal {maximo}")
            if not self.disponible_por_defecto and total > n_libres:
                if alternativos:
                    rep.advertencias.append(
                        f"[Disponibilidad] {doc}: carga principal {total} > bloques disponibles {n_libres}; "
                        f"requiere apoyo de {', '.join(sorted(alternativos))}"
                    )
                else:
                    rep.errores.append(
                        f"[Disponibilidad] {doc}: carga {total} > bloques disponibles {n_libres} (tras aplicar Cambio)")

    # ------------------------------------------------- cambio de disponibilidad
    def aplicar_cambio_disponibilidad(self, df_disponibilidad: pd.DataFrame,
                                      df_cambio: pd.DataFrame) -> pd.DataFrame:
        """
        Aplica la hoja Cambio sobre Disponibilidad y devuelve un DataFrame NUEVO (no muta la entrada).

        - Empareja por (docente_id, dia, bloque_id) con días/IDs normalizados ('martes' == 'Martes', 'D02' == 'D2').
        - Si la combinación existe → sobrescribe `disponible` con `disponible_nuevo`.
        - Si no existe → la agrega como fila nueva (cambio sobre una rejilla dispersa).
        - Agrega columnas de trazabilidad: `modificado` (bool) y `motivo_cambio`.
        - Si un mismo slot aparece varias veces en Cambio, prevalece la última fila.
        - Deja la bitácora en `self.cambios_aplicados` (antes → después, tipo de cambio).
        """
        claves = ["docente_id", "dia", "bloque_id"]
        salida = claves + ["disponible", "modificado", "motivo_cambio"]

        disp = self._normalizar_hoja("Disponibilidad", df_disponibilidad.copy())
        cambio = self._normalizar_hoja("Cambio", df_cambio.copy())
        if "motivo" not in cambio.columns:
            cambio["motivo"] = None

        # Reconciliar IDs tipo 'D02' -> 'D2' respecto a los IDs presentes en disp (o Docentes)
        universo_doc = set(disp["docente_id"].dropna().unique())
        if "Docentes" in self.hojas and "docente_id" in self.hojas["Docentes"].columns:
            universo_doc |= set(self.hojas["Docentes"]["docente_id"].dropna().unique())
        mapa_doc = {_clave_id_canonica(d): d for d in universo_doc}
        disp["docente_id"] = disp["docente_id"].map(lambda v: mapa_doc.get(_clave_id_canonica(v), v))
        cambio["docente_id"] = cambio["docente_id"].map(lambda v: mapa_doc.get(_clave_id_canonica(v), v))

        disp = disp.dropna(subset=claves).drop_duplicates(claves, keep="last")
        if "modificado" not in disp.columns:
            disp["modificado"] = False
            disp["motivo_cambio"] = None
        cambio = cambio.dropna(subset=claves + ["disponible_nuevo"]).drop_duplicates(claves, keep="last")

        self.cambios_aplicados = []
        if cambio.empty:
            disp["disponible"] = disp["disponible"].astype(bool)
            return self._ordenar_disponibilidad(disp[salida]).reset_index(drop=True)

        fusion = disp[salida].merge(cambio[claves + ["disponible_nuevo", "motivo"]],
                                    on=claves, how="outer", indicator=True)
        tiene_cambio = fusion["_merge"] != "left_only"

        # Bitácora: qué cambió realmente (antes → después)
        for _, fila in fusion[tiene_cambio].iterrows():
            antes = None if _es_nulo(fila["disponible"]) else bool(fila["disponible"])
            despues = bool(fila["disponible_nuevo"])
            tipo = "nuevo" if fila["_merge"] == "right_only" else ("sin_efecto" if antes == despues else "actualizado")
            self.cambios_aplicados.append({
                "docente_id": fila["docente_id"], "dia": fila["dia"], "bloque_id": fila["bloque_id"],
                "antes": antes, "despues": despues, "motivo": fila["motivo"], "tipo": tipo,
            })
            logger.info("Cambio disponibilidad %s %s %s: %s → %s (%s)",
                        fila["docente_id"], fila["dia"], fila["bloque_id"], antes, despues, fila["motivo"])

        fusion.loc[tiene_cambio, "disponible"] = fusion.loc[tiene_cambio, "disponible_nuevo"]
        fusion.loc[tiene_cambio, "modificado"] = True
        fusion.loc[tiene_cambio, "motivo_cambio"] = fusion.loc[tiene_cambio, "motivo"]
        fusion["disponible"] = fusion["disponible"].astype(bool)
        fusion["modificado"] = fusion["modificado"].fillna(False).astype(bool)

        return self._ordenar_disponibilidad(fusion[salida]).reset_index(drop=True)

    # ------------------------------------------------- salida para el solver
    def preparar_para_solver(self, *, aplicar_cambio: bool = True, validar: bool = True) -> SolverData:
        """
        Construye `SolverData`. Si `validar=True` y hay errores, lanza DataValidationError.
        La disponibilidad se entrega como rejilla COMPLETA docente × día × bloque.
        """
        if validar:
            self.validar(lanzar=True)

        h = self.hojas
        filas_bloques = sorted(
            ((r.bloque_id, normalizar_hora(r.inicio), normalizar_hora(r.fin)) for r in h["Bloques"].itertuples()),
            key=lambda t: t[1])
        bloques = [Bloque(bid, ini, fin, i) for i, (bid, ini, fin) in enumerate(filas_bloques)]

        cursos = {r.curso_id: Curso(r.curso_id, r.nombre or r.curso_id, int(r.estudiantes))
                  for r in h["Cursos"].itertuples()}
        docentes = {r.docente_id: Docente(r.docente_id, r.nombre or r.docente_id, int(r.max_sesiones_semana))
                    for r in h["Docentes"].itertuples()}
        salones = {r.salon_id: Salon(r.salon_id, r.nombre or r.salon_id, r.tipo, int(r.capacidad))
                   for r in h["Salones"].itertuples()}

        hab_map = self._mapa_habilitados()
        requerimientos: list[Requerimiento] = []
        docentes_compatibles: dict[int, list[str]] = {}
        for i, r in enumerate(h["Carga"].itertuples()):
            clave_asig = _sin_tildes(str(r.asignatura)).strip().lower()
            cands = [r.docente_principal_id]
            for alt in hab_map.get(clave_asig, []):
                if alt in docentes and alt not in cands:
                    cands.append(alt)
            req = Requerimiento(
                id=i,
                curso_id=r.curso_id,
                asignatura=r.asignatura,
                docente_id=r.docente_principal_id,
                sesiones_semana=int(r.sesiones_semana),
                tipo_salon=r.tipo_salon_requerido,
                docentes_habilitados=tuple(cands),
            )
            requerimientos.append(req)
            docentes_compatibles[i] = cands

        # Salones válidos ordenados por capacidad (best-fit primero).
        compatibles = {
            req.id: [s.id for s in sorted(salones.values(), key=lambda s: (s.capacidad, s.id))
                     if s.tipo.lower() == req.tipo_salon.lower()
                     and s.capacidad >= cursos[req.curso_id].estudiantes]
            for req in requerimientos
        }

        disp_df = self._disponibilidad_efectiva(aplicar_cambio=aplicar_cambio)
        dias = self._dias()
        mapa = {(r.docente_id, r.dia, r.bloque_id): bool(r.disponible) for r in disp_df.itertuples()}
        disponibilidad: dict[ClaveDisp, bool] = {
            (d, dia, b.id): mapa.get((d, dia, b.id), self.disponible_por_defecto)
            for d in docentes for dia in dias for b in bloques
        }

        metadatos: dict[str, str] = {}
        if "Leeme" in h and not h["Leeme"].empty:
            for r in h["Leeme"].itertuples():
                if getattr(r, "concepto", None) and getattr(r, "descripcion", None):
                    metadatos[str(r.concepto)] = str(r.descripcion)

        return SolverData(
            dias=dias,
            bloques=bloques,
            cursos=cursos,
            docentes=docentes,
            salones=salones,
            requerimientos=requerimientos,
            disponibilidad=disponibilidad,
            salones_compatibles=compatibles,
            docentes_compatibles=docentes_compatibles,
            habilitados_por_asignatura=hab_map,
            idx_dia={d: i for i, d in enumerate(dias)},
            idx_bloque={b.id: b.indice for b in bloques},
            metadatos=metadatos,
            cambios_aplicados=list(self.cambios_aplicados) if aplicar_cambio else [],
        )

    # ------------------------------------------------------------- utilidades
    def _disponibilidad_efectiva(self, aplicar_cambio: bool = True) -> pd.DataFrame:
        """Disponibilidad limpia, con o sin la hoja Cambio aplicada."""
        cambio = self.hojas["Cambio"] if aplicar_cambio else self.hojas["Cambio"].iloc[0:0]
        return self.aplicar_cambio_disponibilidad(self.hojas["Disponibilidad"], cambio)

    def _dias(self) -> list[str]:
        """Días presentes en Disponibilidad/Cambio en orden canónico; por defecto Lunes–Viernes."""
        presentes: set[str] = set()
        for hoja in ("Disponibilidad", "Cambio"):
            df = self.hojas.get(hoja)
            if df is not None and "dia" in df.columns:
                presentes |= set(df["dia"].dropna())
        return [d for d in DIAS_CANONICOS if d in presentes] or DIAS_CANONICOS[:5]

    @staticmethod
    def _ordenar_disponibilidad(df: pd.DataFrame) -> pd.DataFrame:
        orden_dia = {d: i for i, d in enumerate(DIAS_CANONICOS)}
        return df.sort_values(["docente_id", "dia", "bloque_id"],
                              key=lambda s: s.map(orden_dia) if s.name == "dia" else s)

    @staticmethod
    def _filas(indices: Iterable[int], maximo: int = 8) -> str:
        """Índices pandas → número de fila Excel (encabezado = fila 1)."""
        filas = [str(int(i) + 2) for i in indices]
        return ", ".join(filas[:maximo]) + (f" … (+{len(filas) - maximo})" if len(filas) > maximo else "")
