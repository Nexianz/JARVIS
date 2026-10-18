// Only observed samples enter the chart. No generated prices, backfilled candles or demo data.
export function samplesFor(history, field) {
  return (history ?? []).filter(p => Number.isFinite(p[field]) && Number.isFinite(Date.parse(p.at)))
    .map(p => ({ ...p, timestamp: Date.parse(p.at), value: p[field] }))
    .sort((a, b) => a.timestamp - b.timestamp)
    .filter((p, i, all) => i === 0 || p.timestamp !== all[i - 1].timestamp);
}
export function nearestIndex(points, timestamp) {
  if (!points.length) return -1;
  let lo = 0, hi = points.length - 1;
  while (lo < hi) { const m = Math.floor((lo + hi) / 2); if (points[m].timestamp < timestamp) lo = m + 1; else hi = m; }
  return lo > 0 && timestamp - points[lo - 1].timestamp <= points[lo].timestamp - timestamp ? lo - 1 : lo;
}
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
export function drawSeries(root, { history, field, formatValue, title }) {
  const points = samplesFor(history, field);
  const hadFocus = root.contains(document.activeElement);
  const priorHover = root.dataset.field === field ? Number(root.dataset.hoverAt) : NaN;
  root.dataset.field = field;
  if (!Number.isFinite(priorHover)) delete root.dataset.hoverAt;
  if (!points.length) {
    delete root.dataset.hoverAt;
    root.innerHTML = `<div class="empty-chart"><div class="empty-icon">⌁</div><strong>Ingen målinger å vise ennå</strong><span>Start agenten eller trykk «Skann nå». Grafen bruker bare observerte data.</span></div>`;
    return;
  }
  const W = 680, H = 225, L = 20, R = 25, T = 18, B = 32;
  const low = Math.min(...points.map(p => p.value)), high = Math.max(...points.map(p => p.value));
  const pad = Math.max((high - low) * .2, field === 'equity' ? 2 : high * .00015, .01);
  const min = low - pad, max = high + pad;
  const firstTime = points[0].timestamp, span = points.length > 1 ? Math.max(1, points.at(-1).timestamp - firstTime) : 60000;
  const x = p => L + (W - L - R) * (p.timestamp - firstTime) / span;
  const y = p => T + (H - T - B) * (1 - (p.value - min) / (max - min));
  const time = t => new Date(t).toLocaleTimeString('nb-NO', { hour: '2-digit', minute: '2-digit' });
  // Break the line at collection gaps; spacing is actual elapsed time, not sample index.
  const paths = []; let current = [];
  for (let i = 0; i < points.length; i++) {
    if (i && (points[i].timestamp - points[i - 1].timestamp > 180000 || field === 'ethUsd' && (points[i].ethSource || 'Chainlink-orakel') !== (points[i - 1].ethSource || 'Chainlink-orakel'))) { paths.push(current); current = []; }
    current.push(points[i]);
  }
  paths.push(current);
  const lines = paths.map(group => `<path d="${group.map((p, i) => `${i ? 'L' : 'M'}${x(p).toFixed(2)},${y(p).toFixed(2)}`).join(' ')}" fill="none" stroke="#bb9bf4" stroke-width="2"/>`).join('');
  const grid = [0, 1, 2, 3].map(i => { const yy = T + (H - T - B) * i / 3; return `<line x1="${L}" x2="${W - R}" y1="${yy}" y2="${yy}" stroke="#2b2e3a" stroke-dasharray="3 5"/><text x="${W - R}" y="${yy - 5}" text-anchor="end" fill="#7d879d" font-size="8">${esc(formatValue(max - (max - min) * i / 3))}</text>`; }).join('');
  const last = points.at(-1);
  root.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title)}"><title>${esc(title)}. Hover, trykk eller bruk piltaster for detaljer.</title>${grid}${lines}<circle cx="${x(last)}" cy="${y(last)}" r="3" fill="#d4baff"/><g class="chart-crosshair" visibility="hidden"><line x1="0" x2="0" y1="${T}" y2="${H - B}" stroke="#a39bb9" stroke-dasharray="4 4"/><circle r="4" fill="#d4baff" stroke="#191c23" stroke-width="2"/></g><text x="${L}" y="${H - 7}" fill="#8892a8" font-size="9">${esc(time(firstTime))}</text><text x="${W - R}" y="${H - 7}" text-anchor="end" fill="#8892a8" font-size="9">${esc(time(last.timestamp))}</text><rect class="chart-hit" x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent" tabindex="0" role="slider" aria-label="${esc(title)}: velg målepunkt" aria-valuemin="1" aria-valuemax="${points.length}" aria-valuenow="${points.length}" aria-orientation="horizontal"/></svg><div class="chart-tooltip" role="status" hidden></div>`;
  const svg = root.querySelector('svg'), hit = root.querySelector('.chart-hit'), cross = root.querySelector('.chart-crosshair'), tooltip = root.querySelector('.chart-tooltip');
  let selected = points.length - 1;
  function show(index) {
    selected = Math.max(0, Math.min(points.length - 1, index)); const p = points[selected];
    root.dataset.hoverAt = String(p.timestamp);
    const detail = `${new Date(p.timestamp).toLocaleString('nb-NO', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' })} · blokk ${p.block}`;
    const source = field === 'equity' ? 'BEREGNET · simulert egenkapital' : `MÅLT · ${p.ethSource || 'Chainlink-orakel (eldre punkt)'}`;
    tooltip.innerHTML = `<strong>${esc(formatValue(p.value))}</strong><span>${esc(detail)}</span><small>${esc(source)}</small>`;
    tooltip.hidden = false;
    cross.setAttribute('visibility', 'visible'); const line = cross.querySelector('line'), circle = cross.querySelector('circle');
    line.setAttribute('x1', x(p)); line.setAttribute('x2', x(p)); circle.setAttribute('cx', x(p)); circle.setAttribute('cy', y(p));
    hit.setAttribute('aria-valuenow', String(selected + 1)); hit.setAttribute('aria-valuetext', `${formatValue(p.value)}, ${detail}, ${source}`);
    // Position through SVG's transform, including letterboxing on narrow screens. CSS classes avoid inline-style CSP exceptions.
    const pt = svg.createSVGPoint(); pt.x = x(p); pt.y = y(p); const screen = pt.matrixTransform(svg.getScreenCTM()); const rect = root.getBoundingClientRect();
    tooltip.classList.toggle('tooltip-right', screen.x - rect.left > rect.width / 2);
  }
  function hide() { tooltip.hidden = true; cross.setAttribute('visibility', 'hidden'); delete root.dataset.hoverAt; }
  function pointer(e) {
    const matrix = svg.getScreenCTM(); if (!matrix) return;
    const p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY; const local = p.matrixTransform(matrix.inverse());
    show(nearestIndex(points, firstTime + Math.max(0, Math.min(1, (local.x - L) / (W - L - R))) * span));
  }
  hit.addEventListener('pointermove', pointer); hit.addEventListener('pointerdown', pointer);
  hit.addEventListener('pointerleave', e => { if (e.pointerType !== 'touch' && document.activeElement !== hit) hide(); });
  hit.addEventListener('focus', () => show(selected)); hit.addEventListener('blur', hide);
  hit.addEventListener('keydown', e => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End', 'Escape'].includes(e.key)) return;
    e.preventDefault(); if (e.key === 'Escape') { hide(); return; }
    show(e.key === 'Home' ? 0 : e.key === 'End' ? points.length - 1 : selected + (e.key === 'ArrowRight' ? 1 : -1));
  });
  if (Number.isFinite(priorHover)) show(nearestIndex(points, priorHover));
  if (hadFocus) hit.focus({ preventScroll: true });
}
