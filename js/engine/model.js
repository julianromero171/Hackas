/**
 * Modelo matemático del problema de horarios (School Timetabling Problem).
 *
 * Variable de decisión conceptual:  X[c,m,p,a,d,b] ∈ {0,1}
 *   c = curso, m = asignatura, p = docente, a = aula, d = día, b = bloque.
 *
 * Representación compacta usada por el motor: cada curso tiene una permutación de sus
 * lecciones (1 lección = 1 hora de una asignatura) sobre los S = días × bloques slots.
 *   grid[c][t] = id de lección | -1 (libre)
 * Así la restricción "0 cruces por curso" se cumple POR CONSTRUCCIÓN, y el docente (p) y
 * el tipo de aula (a) quedan determinados por la lección. El aula concreta se asigna con
 * un emparejamiento por capacidad en cada slot.
 */

export const HARD_WEIGHT = 1000;
export const AVOID_PENALTY = 4;
export const DEFAULT_WEIGHTS = Object.freeze({ gaps: 6, fatigue: 5, morning: 4, equity: 4 });

/**
 * Construye el problema indexado a partir de los datos JSON y de las reglas del copiloto.
 * @param {object} data   Datos del colegio (ver data/school.json)
 * @param {Array}  rules  Reglas generadas por el agente NLP
 */
export function buildProblem(data, rules = []) {
  const J = data.jornada;
  const days = J.dias.length;
  const B = J.bloquesPorDia;
  const S = days * B;
  const teachers = data.docentes;
  const subjects = data.asignaturas;
  const rooms = data.aulas;
  const courses = data.cursos;
  const nT = teachers.length, nS = subjects.length, nR = rooms.length, nC = courses.length;
  const tIdx = new Map(teachers.map((t, i) => [t.id, i]));
  const sIdx = new Map(subjects.map((s, i) => [s.id, i]));
  const rIdx = new Map(rooms.map((r, i) => [r.id, i]));
  const issues = [];

  // Recreos: rompen la consecutividad entre bloque b y b+1
  const breakAfter = new Uint8Array(B);
  for (const r of J.recreos || []) {
    const b = r.despuesDeBloque - 1;
    if (b >= 0 && b < B - 1) breakAfter[b] = 1;
  }

  // Tipos de espacio y aulas disponibles por tipo (ordenadas por capacidad ascendente)
  const types = [...new Set([...rooms.map((r) => r.tipo), ...subjects.map((s) => s.tipoEspacio)])];
  const typeId = new Map(types.map((t, i) => [t, i]));
  const typeRooms = types.map(() => []);
  rooms.forEach((r, ri) => typeRooms[typeId.get(r.tipo)].push(ri));
  typeRooms.forEach((list) => list.sort((a, b) => rooms[a].capacidad - rooms[b].capacidad));
  const maxSize = Math.max(...courses.map((c) => c.estudiantes));
  const typeSupply = typeRooms.map((l) => l.length);
  const typeSimple = typeRooms.map((l) => l.every((ri) => rooms[ri].capacidad >= maxSize));
  const typeScarce = typeSupply.map((n) => n < nC);

  // Lecciones
  const lessons = [];
  const courseLessons = courses.map(() => []);
  const allowedPerDay = courses.map(() => new Uint8Array(nS));
  const heavyCap = new Uint8Array(nC);
  courses.forEach((c, ci) => {
    let heavyHours = 0;
    for (const item of c.plan) {
      const si = sIdx.get(item.asignatura);
      const pi = tIdx.get(item.docente);
      if (si === undefined) { issues.push({ nivel: 'error', msg: `${c.nombre}: asignatura desconocida "${item.asignatura}".` }); continue; }
      if (pi === undefined) { issues.push({ nivel: 'error', msg: `${c.nombre}: docente desconocido "${item.docente}".` }); continue; }
      const sub = subjects[si];
      const ty = typeId.get(sub.tipoEspacio);
      if (!typeRooms[ty].some((ri) => rooms[ri].capacidad >= c.estudiantes)) {
        issues.push({ nivel: 'error', msg: `No existe ${data.tiposEspacio?.[sub.tipoEspacio] || sub.tipoEspacio} con capacidad para ${c.nombre} (${c.estudiantes} estudiantes).` });
      }
      allowedPerDay[ci][si] = Math.ceil(item.horas / days);
      const heavy = sub.cargaCognitiva === 'alta';
      if (heavy) heavyHours += item.horas;
      for (let h = 0; h < item.horas; h++) {
        const id = lessons.length;
        lessons.push({ id, c: ci, s: si, p: pi, type: ty, heavy, size: c.estudiantes });
        courseLessons[ci].push(id);
      }
    }
    heavyCap[ci] = Math.max(1, Math.ceil(heavyHours / days));
    if (courseLessons[ci].length > S) {
      issues.push({ nivel: 'error', msg: `${c.nombre}: el plan de estudios (${courseLessons[ci].length} h) excede los ${S} bloques semanales.` });
    }
  });

  // Disponibilidad docente (ficha + reglas del copiloto)
  const unavailable = teachers.map(() => new Uint8Array(S));
  const unavailReason = teachers.map(() => new Array(S).fill(null));
  teachers.forEach((t, pi) => {
    for (const nd of t.noDisponible || []) {
      const d = J.dias.indexOf(nd.dia);
      if (d < 0) continue;
      for (const b1 of nd.bloques || []) {
        const b = b1 - 1;
        if (b >= 0 && b < B) {
          unavailable[pi][d * B + b] = 1;
          unavailReason[pi][d * B + b] = nd.motivo || 'Disponibilidad registrada en la ficha docente';
        }
      }
    }
  });

  const forbidden = subjects.map(() => new Uint8Array(S));
  const forbidReason = subjects.map(() => new Array(S).fill(null));
  const softSlot = subjects.map(() => new Float32Array(S));
  const allDays = [...Array(days).keys()];

  for (const rule of rules) {
    if (!rule || rule.enabled === false) continue;
    const rDays = rule.days && rule.days.length ? rule.days : allDays;
    if (rule.type === 'teacher_unavailable') {
      const pi = tIdx.get(rule.teacherId);
      if (pi === undefined) continue;
      const cells = rule.slots && rule.slots.length
        ? rule.slots
        : rDays.flatMap((d) => (rule.blocks || []).map((b) => [d, b]));
      for (const [d, b] of cells) {
        if (d < days && b < B && d >= 0 && b >= 0) {
          unavailable[pi][d * B + b] = 1;
          unavailReason[pi][d * B + b] = `Regla IA: “${rule.text || rule.label || ''}”`;
        }
      }
    } else if (rule.type === 'subject_avoid') {
      for (const sid of rule.subjectIds || []) {
        const si = sIdx.get(sid);
        if (si === undefined) continue;
        for (const d of rDays) for (const b of rule.blocks || []) {
          if (d >= days || b >= B) continue;
          const t = d * B + b;
          if (rule.hard) { forbidden[si][t] = 1; forbidReason[si][t] = rule.text || rule.label; }
          else softSlot[si][t] += AVOID_PENALTY;
        }
      }
    } else if (rule.type === 'subject_prefer_morning') {
      for (const sid of rule.subjectIds || []) {
        const si = sIdx.get(sid);
        if (si === undefined) continue;
        for (let t = 0; t < S; t++) softSlot[si][t] += t % B;
      }
    }
  }

  // Validaciones estáticas de factibilidad
  const teacherLoad = new Array(nT).fill(0);
  lessons.forEach((l) => teacherLoad[l.p]++);
  const teacherAvail = unavailable.map((u) => S - u.reduce((a, b) => a + b, 0));
  teachers.forEach((t, pi) => {
    if (teacherLoad[pi] > t.maxHorasSemana) {
      issues.push({ nivel: 'error', msg: `${t.nombre}: ${teacherLoad[pi]} h asignadas superan su límite semanal de ${t.maxHorasSemana} h.` });
    }
    if (teacherLoad[pi] > teacherAvail[pi]) {
      issues.push({ nivel: 'error', msg: `${t.nombre}: necesita ${teacherLoad[pi]} bloques pero solo tiene ${teacherAvail[pi]} disponibles.` });
    }
  });
  types.forEach((ty, i) => {
    const demand = lessons.reduce((a, l) => a + (l.type === i ? 1 : 0), 0);
    if (demand > typeSupply[i] * S) {
      issues.push({ nivel: 'error', msg: `Demanda de ${data.tiposEspacio?.[ty] || ty} (${demand} h) supera la oferta (${typeSupply[i] * S} bloques).` });
    }
  });

  let maxSlotPenalty = 0;
  for (const l of lessons) {
    const row = softSlot[l.s];
    let m = 0;
    for (let t = 0; t < S; t++) if (row[t] > m) m = row[t];
    maxSlotPenalty += m;
  }

  return {
    data, days, B, S, nT, nS, nR, nC,
    teachers, subjects, rooms, courses, tIdx, sIdx, rIdx,
    lessons, courseLessons, breakAfter,
    types, typeRooms, typeSupply, typeSimple, typeScarce,
    homeroom: courses.map((c) => (rIdx.has(c.aulaBase) ? rIdx.get(c.aulaBase) : -1)),
    unavailable, unavailReason, forbidden, forbidReason, softSlot,
    allowedPerDay, heavyCap, teacherLoad, teacherAvail,
    maxSlotPenalty,
    heavyTotal: lessons.reduce((a, l) => a + (l.heavy ? 1 : 0), 0),
    issues,
    blocking: issues.some((i) => i.nivel === 'error'),
  };
}

/** Verifica que un grid sea una permutación válida de las lecciones de cada curso. */
export function isValidGrid(P, grid) {
  if (!Array.isArray(grid) || grid.length !== P.nC) return false;
  const seen = new Uint8Array(P.lessons.length);
  for (let c = 0; c < P.nC; c++) {
    const row = grid[c];
    if (!row || row.length !== P.S) return false;
    let count = 0;
    for (let t = 0; t < P.S; t++) {
      const l = row[t];
      if (l < 0) continue;
      if (l >= P.lessons.length || P.lessons[l].c !== c || seen[l]) return false;
      seen[l] = 1;
      count++;
    }
    if (count !== P.courseLessons[c].length) return false;
  }
  return true;
}
