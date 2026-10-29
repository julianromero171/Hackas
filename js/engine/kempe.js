/**
 * Cadenas de Kempe para timetabling.
 *
 * Dado un curso c0 y dos slots (t1, t2), la cadena es la componente conexa del grafo
 * de conflictos restringido a las lecciones ubicadas en t1 ∪ t2. Dos lecciones están
 * enlazadas si comparten docente o un tipo de espacio escaso. Intercambiar t1↔t2 en
 * TODOS los cursos de la cadena preserva la ausencia de cruces docentes/aulas: es el
 * movimiento clásico de "reparación de Kempe" del coloreo de grafos.
 */
export function kempeChain(state, c0, t1, t2) {
  const P = state.P, g = state.grid, L = P.lessons, nC = P.nC;
  const inSet = new Uint8Array(nC);
  const stack = [c0];
  const out = [c0];
  inSet[c0] = 1;
  while (stack.length) {
    const x = stack.pop();
    const a = g[x][t1], b = g[x][t2];
    for (let y = 0; y < nC; y++) {
      if (inSet[y]) continue;
      const ya = g[y][t1], yb = g[y][t2];
      if ((a >= 0 && yb >= 0 && linked(P, L[a], L[yb])) || (b >= 0 && ya >= 0 && linked(P, L[b], L[ya]))) {
        inSet[y] = 1;
        stack.push(y);
        out.push(y);
      }
    }
  }
  return out;
}

function linked(P, l1, l2) {
  return l1.p === l2.p || (l1.type === l2.type && (P.typeScarce[l1.type] || !P.typeSimple[l1.type]));
}
