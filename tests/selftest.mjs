/**
 * Autotest del motor JS y del agente NLP (sin dependencias).
 *   node tests/selftest.mjs
 */
import { readFileSync } from 'node:fs';
import { solve } from '../js/engine/solver.js';
import { buildProblem } from '../js/engine/model.js';
import { explainSwap } from '../js/engine/explain.js';
import { parseInstruction, DEMO_PROMPTS } from '../js/ai/nlp.js';

const data = JSON.parse(readFileSync(new URL('../data/school.json', import.meta.url), 'utf8'));
let failures = 0;
const check = (cond, msg) => {
  if (cond) console.log(`  ✔ ${msg}`);
  else { failures++; console.error(`  ✘ ${msg}`); }
};
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// ---------------------------------------------------------------- NLP
console.log('\n▶ Agente NLP (prompts de demostración)');
const [p1, p2, p3, p4, p5, p6] = DEMO_PROMPTS.map((t) => parseInstruction(t, data));

const r1 = p1.actions[0]?.rule;
check(r1?.type === 'teacher_unavailable' && r1.teacherId === 'P01' && eq(r1.days, [4]) && eq(r1.blocks, [4, 5]), `P1 Carlos Ruiz · Viernes · B5–B6  → ${r1?.formal?.replace(/\n/g, ' | ')}`);
const r2 = p2.actions[0]?.rule;
check(r2?.type === 'teacher_unavailable' && r2.teacherId === 'P03' && eq(r2.days, [0]) && eq(r2.blocks, [0, 1]), `P2 Laura Méndez · Lunes · B1–B2`);
const r3 = p3.actions[0]?.rule;
check(r3?.type === 'subject_avoid' && eq(r3.subjectIds.sort(), ['FIS', 'MAT']) && eq(r3.blocks, [4, 5]) && !r3.hard && p3.actions.length === 1, `P3 Evitar MAT+FIS en B5–B6 (blanda, sin confundir con Ed. Física)`);
check(p4.actions.length === 2 && p4.actions.some((a) => a.changes?.gaps === 10) && p4.actions.some((a) => a.changes?.fatigue === 10), 'P4 Pesos: huecos=10, fatiga=10');
const r5 = p5.actions[0]?.rule;
check(r5?.type === 'teacher_unavailable' && r5.teacherId === 'P07' && eq(r5.days, [2]) && eq(r5.blocks, [3, 4, 5]), 'P5 Julián Ríos · Miércoles · tarde (B4–B6)');
const r6 = p6.actions[0]?.rule;
check(r6?.type === 'subject_prefer_morning' && eq(r6.subjectIds, ['MAT']), 'P6 Priorizar Matemáticas en la mañana');

const extra = [
  ['La profesora de química no puede los jueves', (r) => r.actions[0]?.rule?.teacherId === 'P08'],
  ['Nunca programar Educación Física en el bloque 1', (r) => r.actions[0]?.rule?.hard === true && eq(r.actions[0].rule.subjectIds, ['EDF']) && eq(r.actions[0].rule.blocks, [0])],
  ['Ana Torres solo puede de lunes a miércoles', (r) => r.actions[0]?.rule?.only === true && r.actions[0].rule.slots.length === 12],
  ['deshacer', (r) => r.actions[0]?.kind === 'undo'],
  ['ayuda', (r) => r.actions[0]?.kind === 'help'],
];
for (const [t, fn] of extra) check(fn(parseInstruction(t, data)), `Extra: “${t}”`);

// ---------------------------------------------------------------- Motor
console.log('\n▶ Motor híbrido (CSP + Kempe + SA)');
const demoRules = [r1, r2, r3, r5, r6].filter(Boolean);
const weights = { gaps: 10, fatigue: 10, morning: 4, equity: 4 };
const runs = 12;
let hardSum = 0, msSum = 0, scoreSum = 0;
for (let i = 0; i < runs; i++) {
  const res = solve({ data, rules: i % 2 ? demoRules : [], weights, seed: 1000 + i });
  hardSum += res.metrics.hard.total;
  msSum += res.stats.ms;
  scoreSum += res.metrics.score;
}
check(hardSum === 0, `${runs} corridas → 0 conflictos duros en todas (total=${hardSum})`);
console.log(`    tiempo medio ${(msSum / runs).toFixed(0)} ms · score medio ${(scoreSum / runs).toFixed(1)}%`);

const res = solve({ data, rules: demoRules, weights, seed: 7 });
const P = buildProblem(data, demoRules);
const L = P.lessons;
let carlosFri = 0;
res.grid.forEach((row) => row.forEach((l, t) => {
  if (l >= 0 && L[l].p === 0 && Math.floor(t / P.B) === 4 && t % P.B >= 4) carlosFri++;
}));
check(carlosFri === 0, 'Carlos Ruiz sin clases el viernes B5–B6');
check(res.metrics.hard.teacherClashes === 0 && res.metrics.hard.roomConflicts === 0, 'Sin cruces docentes ni de aulas');

// Warm start
const warm = solve({ data, rules: demoRules, weights, warmGrid: res.grid, seed: 8, timeLimitMs: 400 });
check(warm.stats.warm && warm.metrics.hard.total === 0, `Re-optimización incremental (warm start) en ${warm.stats.ms.toFixed(0)} ms`);

// Click-to-swap: buscar un swap inválido y uno válido
let invalidFound = false, validFound = false;
outer: for (let t1 = 0; t1 < P.S; t1++) {
  for (let t2 = t1 + 1; t2 < P.S; t2++) {
    const ex = explainSwap(P, res.grid, weights, 0, t1, t2);
    if (!ex.ok && ex.messages.length && !invalidFound) invalidFound = true;
    if (ex.ok && !validFound) validFound = true;
    if (invalidFound && validFound) break outer;
  }
}
check(invalidFound && validFound, 'Click-to-Swap: detecta intercambios válidos e inválidos con explicación');

// Infactibilidad estática detectada
const bad = buildProblem(data, [{ type: 'teacher_unavailable', teacherId: 'P01', days: [0, 1, 2, 3], blocks: [0, 1, 2, 3, 4, 5] }]);
check(bad.blocking, 'Detecta restricción imposible (docente sin bloques suficientes)');

console.log(failures ? `\n✘ ${failures} prueba(s) fallaron\n` : '\n✔ Todas las pruebas pasaron\n');
process.exit(failures ? 1 : 0);
