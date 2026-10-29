"""Modelo de datos (Pydantic v2): Docentes, Asignaturas, Aulas, Jornada/Bloques, Cursos y reglas."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Recreo(BaseModel):
    despuesDeBloque: int = Field(ge=1, description="El recreo ocurre después de este bloque (1-based).")
    duracion: int = Field(ge=5, le=120, description="Minutos.")
    nombre: str = "Recreo"


class Jornada(BaseModel):
    dias: list[str] = Field(min_length=1)
    bloquesPorDia: int = Field(ge=1, le=12)
    duracionBloque: int = Field(50, ge=30, le=90, description="Duración de la hora académica: 45, 50 o 60 min.")
    horaInicio: str = Field("07:00", pattern=r"^\d{2}:\d{2}$")
    recreos: list[Recreo] = []


class Aula(BaseModel):
    id: str
    nombre: str
    tipo: str = Field(description="estandar | lab_ciencias | lab_sistemas | polideportivo | …")
    capacidad: int = Field(gt=0)


class Asignatura(BaseModel):
    id: str
    nombre: str
    tipoEspacio: str = "estandar"
    cargaCognitiva: Literal["alta", "media", "baja"] = "media"
    color: str = "#64748b"
    alias: list[str] = []


class NoDisponible(BaseModel):
    dia: str
    bloques: list[int] = Field(description="Bloques 1-based.")
    motivo: Optional[str] = None


class Docente(BaseModel):
    id: str
    nombre: str
    asignaturas: list[str] = []
    maxHorasSemana: int = Field(gt=0)
    noDisponible: list[NoDisponible] = []


class ItemPlan(BaseModel):
    asignatura: str
    horas: int = Field(ge=1)
    docente: str


class Curso(BaseModel):
    id: str
    nombre: str
    grado: int
    estudiantes: int = Field(gt=0)
    aulaBase: Optional[str] = None
    plan: list[ItemPlan]


class SchoolData(BaseModel):
    model_config = ConfigDict(extra="allow")
    institucion: str = ""
    jornada: Jornada
    tiposEspacio: dict[str, str] = {}
    aulas: list[Aula]
    asignaturas: list[Asignatura]
    docentes: list[Docente]
    cursos: list[Curso]

    @model_validator(mode="after")
    def _check_refs(self) -> "SchoolData":
        subj = {s.id for s in self.asignaturas}
        teach = {d.id for d in self.docentes}
        for c in self.cursos:
            for it in c.plan:
                if it.asignatura not in subj:
                    raise ValueError(f"{c.nombre}: asignatura desconocida {it.asignatura}")
                if it.docente not in teach:
                    raise ValueError(f"{c.nombre}: docente desconocido {it.docente}")
        return self


class Rule(BaseModel):
    """Regla generada por el copiloto NLP (bloques y días 0-based)."""
    model_config = ConfigDict(extra="allow")
    id: Optional[str] = None
    type: Literal["teacher_unavailable", "subject_avoid", "subject_prefer_morning"]
    teacherId: Optional[str] = None
    subjectIds: list[str] = []
    days: list[int] = []
    blocks: list[int] = []
    slots: list[list[int]] = []
    hard: bool = False
    enabled: bool = True
    text: str = ""


class Weights(BaseModel):
    gaps: float = Field(6, ge=0, le=10)
    fatigue: float = Field(5, ge=0, le=10)
    morning: float = Field(4, ge=0, le=10)
    equity: float = Field(4, ge=0, le=10)


class SolveRequest(BaseModel):
    data: Optional[SchoolData] = None
    rules: list[Rule] = []
    weights: Weights = Weights()
    timeLimit: float = Field(10, gt=0, le=120)
    workers: int = Field(8, ge=1, le=32)


Horario = dict[str, list[Optional[str]]]


class SolveResponse(BaseModel):
    status: str
    engine: str = "Google OR-Tools CP-SAT"
    wallTimeMs: float = 0
    objective: Optional[float] = None
    branches: int = 0
    horario: Optional[Horario] = None
    metrics: Optional[dict] = None
    issues: list[str] = []


class ValidateRequest(BaseModel):
    data: Optional[SchoolData] = None
    rules: list[Rule] = []
    weights: Weights = Weights()
    horario: Horario
