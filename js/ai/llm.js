/**
 * Modo LLM opcional (Google Gemini). Si el usuario configura una API key, la instrucción
 * se traduce con el LLM a acciones JSON estructuradas; se validan contra el catálogo y se
 * convierten con las mismas funciones del parser local. Ante cualquier error, la app
 * vuelve automáticamente al parser determinista.
 */
import { finalizeRule } from './nlp.js';

export async function parseWithGemini(text, data, { key, model = 'gemini-2.5-flash' }) {
  const B = data.jornada.bloquesPorDia;
  const half = Math.ceil(B / 2);
  const system = `Eres el traductor NLP→CSP de un generador de horarios escolares. Convierte la instrucción del coordinador académico en acciones JSON.
Docentes: ${data.docentes.map((d) => `${d.id}=${d.nombre}`).join('; ')}
Asignaturas: ${data.asignaturas.map((s) => `${s.id}=${s.nombre}`).join('; ')}
Días (índice): ${data.jornada.dias.map((d, i) => `${i}=${d}`).join(', ')}
Bloques: 0..${B - 1} (0 = primera hora, ${B - 1} = última). Mañana = 0..${half - 1}; tarde = ${half}..${B - 1}. "Últimas horas" sin número = últimos 2 bloques.
Responde SOLO JSON: {"actions":[...]} con acciones de estos tipos:
{"type":"teacher_unavailable","teacherId":"P01","days":[4],"blocks":[4,5]}
{"type":"subject_avoid","subjectIds":["MAT"],"days":[],"blocks":[4,5],"hard":false}
{"type":"subject_prefer_morning","subjectIds":["MAT"]}
{"type":"weights","changes":{"gaps":10}}   (claves posibles: gaps, fatigue, morning, equity; valores 0..10)
{"type":"clear"} | {"type":"undo"} | {"type":"help"}
Usa "hard":true solo si la instrucción es absoluta (nunca, prohibido). Si no entiendes, responde {"actions":[]}.`;

  const url = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent?key=${encodeURIComponent(key)}`;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 9000);
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: ctrl.signal,
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: system }] },
        contents: [{ role: 'user', parts: [{ text }] }],
        generationConfig: { responseMimeType: 'application/json', temperature: 0 },
      }),
    });
    if (!res.ok) throw new Error(`Gemini HTTP ${res.status}`);
    const json = await res.json();
    const raw = json?.candidates?.[0]?.content?.parts?.[0]?.text;
    if (!raw) throw new Error('Respuesta vacía de Gemini');
    return toParsed(JSON.parse(raw), text, data);
  } finally {
    clearTimeout(timer);
  }
}

function toParsed(out, text, data) {
  const B = data.jornada.bloquesPorDia, nD = data.jornada.dias.length;
  const tIds = new Set(data.docentes.map((d) => d.id));
  const sIds = new Set(data.asignaturas.map((s) => s.id));
  const okDays = (a) => (Array.isArray(a) ? a.filter((d) => Number.isInteger(d) && d >= 0 && d < nD) : []);
  const okBlocks = (a) => (Array.isArray(a) ? a.filter((b) => Number.isInteger(b) && b >= 0 && b < B) : []);
  const res = { source: 'gemini', understood: false, actions: [], entities: {}, notes: [] };

  for (const a of out?.actions || []) {
    switch (a?.type) {
      case 'teacher_unavailable': {
        if (!tIds.has(a.teacherId)) break;
        const days = okDays(a.days), blocks = okBlocks(a.blocks);
        const rule = { type: 'teacher_unavailable', teacherId: a.teacherId, days: days.length ? days : [...Array(nD).keys()], blocks: blocks.length ? blocks : [...Array(B).keys()], hard: true };
        res.actions.push({ kind: 'rule', rule: finalizeRule(rule, text, data) });
        break;
      }
      case 'subject_avoid': {
        const subjectIds = (a.subjectIds || []).filter((s) => sIds.has(s));
        const blocks = okBlocks(a.blocks);
        if (!subjectIds.length || !blocks.length) break;
        const rule = { type: 'subject_avoid', subjectIds, days: okDays(a.days), blocks, hard: !!a.hard };
        res.actions.push({ kind: 'rule', rule: finalizeRule(rule, text, data) });
        break;
      }
      case 'subject_prefer_morning': {
        const subjectIds = (a.subjectIds || []).filter((s) => sIds.has(s));
        if (!subjectIds.length) break;
        res.actions.push({ kind: 'rule', rule: finalizeRule({ type: 'subject_prefer_morning', subjectIds }, text, data) });
        break;
      }
      case 'weights': {
        for (const [k, v] of Object.entries(a.changes || {})) {
          if (['gaps', 'fatigue', 'morning', 'equity'].includes(k) && Number.isFinite(v)) {
            res.actions.push({ kind: 'weights', key: k, changes: { [k]: Math.max(0, Math.min(10, Math.round(v))) } });
          }
        }
        break;
      }
      case 'clear': case 'undo': case 'help':
        res.actions.push({ kind: a.type });
        break;
      default:
        break;
    }
  }
  res.understood = res.actions.length > 0;
  return res;
}
