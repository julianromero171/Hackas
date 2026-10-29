/**
 * Cálculo de la grilla horaria a partir de la jornada (duración de bloque 45/50/60 min y recreos).
 */
const toMin = (hhmm = '07:00') => {
  const [h, m] = hhmm.split(':').map(Number);
  return h * 60 + (m || 0);
};
const fmt = (min) => `${String(Math.floor(min / 60) % 24).padStart(2, '0')}:${String(min % 60).padStart(2, '0')}`;

/**
 * @returns {Array<{bloque:number,inicio:string,fin:string}|{recreo:true,nombre:string,inicio:string,fin:string,duracion:number}>}
 */
export function buildSchedule(jornada) {
  const rows = [];
  let cur = toMin(jornada.horaInicio);
  const dur = jornada.duracionBloque || 50;
  const B = jornada.bloquesPorDia;
  for (let b = 0; b < B; b++) {
    rows.push({ bloque: b, inicio: fmt(cur), fin: fmt(cur + dur) });
    cur += dur;
    const br = (jornada.recreos || []).find((r) => r.despuesDeBloque === b + 1);
    if (br && b < B - 1) {
      rows.push({ recreo: true, nombre: br.nombre || 'Recreo', inicio: fmt(cur), fin: fmt(cur + br.duracion), duracion: br.duracion });
      cur += br.duracion;
    }
  }
  return rows;
}

export const blockTimes = (jornada) => buildSchedule(jornada).filter((r) => !r.recreo);
