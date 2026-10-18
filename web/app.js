const $ = id => document.getElementById(id);
const nf = new Intl.NumberFormat('nb-NO', { maximumFractionDigits: 2 });
const integer = new Intl.NumberFormat('nb-NO', { maximumFractionDigits: 0 });
const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
const money = n => nf.format(Number(n) || 0);
const safe = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const time = s => new Date(s).toLocaleTimeString('nb-NO', { hour: '2-digit', minute: '2-digit' });
let state, token = '', chartMode = 'equity', busy = false, flashMessage = '';
function alertMessage(text) { $('alert').textContent = text; $('alert').hidden = !text; }
async function request(body) {
  const options = body ? { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify(body) } : {};
  const r = await fetch('/api/agent', { ...options, cache: 'no-store' });
  let data; try { data = await r.json(); } catch { throw Error('Serverfunksjonen svarte ikke. Kontroller at siden er deployet med Netlify Functions.'); }
  if (!r.ok) { if (r.status === 401) { token = ''; $('owner-dialog').showModal(); } throw Error(data.error || 'Serveren kunne ikke svare.'); }
  return data;
}
async function refresh() {
  if (busy) return;
  try { state = await request(); render(); }
  catch (e) { alertMessage(e.message); $('agent-status').textContent = 'Ingen serverforbindelse'; }
}
async function act(action, extra = {}) {
  if (!token) { $('owner-dialog').showModal(); return; }
  busy = true; for (const id of ['scan', 'toggle']) $(id).disabled = true;
  try {
    const data = await request({ action, ...extra });
    state = data.state; flashMessage = data.skipped ? 'En skanning pågår eller ble nylig kjørt. Vent omtrent ett minutt.' : ''; render();
  } catch (e) { alertMessage(e.message); }
  finally { busy = false; for (const id of ['scan', 'toggle']) $(id).disabled = false; }
}
function render() {
  if (!state) return;
  const m = state.market, c = state.counters, latest = state.decisions[0];
  const fresh = m && Date.now() - Date.parse(m.observedAt) < 180000;
  $('agent-status').textContent = state.busy ? 'Agenten analyserer' : state.running ? fresh ? 'Agenten er aktiv' : 'Venter på ferske data' : 'Agenten er pauset';
  $('status-light').classList.toggle('running', state.running && Boolean(fresh));
  $('market-live').textContent = fresh ? 'FERSKE DATA' : 'VENTER';
  $('engine').textContent = state.capabilities.engine === 'openai' ? 'AI + faste risikogrenser' : 'Regelbasert agent';
  $('toggle').innerHTML = state.running ? 'Pause agent <span>Ⅱ</span>' : 'Start agent <span>↗</span>';
  $('last-update').textContent = m ? `Målt ${time(m.observedAt)}` : 'Ingen måling ennå';
  $('balance').innerHTML = `${money(state.balance)} <small>NOK</small>`;
  const pnl = state.balance - state.startNok;
  $('pnl').textContent = `${pnl >= 0 ? '+' : ''}${money(pnl)} NOK · BEREGNET paper-PnL`;
  $('pnl').className = pnl > 0 ? 'positive' : pnl < 0 ? 'negative' : '';
  $('eth').textContent = m ? usd.format(m.ethUsd) : '—';
  const best = m?.candidates[0];
  $('best').innerHTML = best ? `${money(best.netNok)} <small>NOK</small>` : '—';
  $('best').className = `metric-value ${best ? best.netNok > 0 ? 'positive' : 'negative' : ''}`;
  $('count').textContent = integer.format(c.wins + c.failed);
  $('count-note').textContent = `${c.wins} antatte fills · ${c.failed} simulerte feil`;
  $('drawdown').textContent = `Beregnet maks drawdown: ${money(state.maxDrawdown * 100)} %`;
  $('samples').textContent = `${state.history.length} målte tidspunkter`;
  $('block').textContent = m ? `Blokk ${integer.format(m.block)}` : 'Blokk —';
  $('chart-value').textContent = chartMode === 'equity' ? `${money(state.balance)} NOK` : m ? usd.format(m.ethUsd) : '—';
  $('channel').value = state.channel; $('channel').disabled = state.running;
  const issues = [];
  if (!state.capabilities.rpcConfigured || !state.capabilities.adminConfigured) issues.push('Oppsett mangler: eieren må legge inn Alchemy-tilgang og eierpassord i Netlify.');
  if (state.lastError) issues.push(`Siste skanning feilet: ${state.lastError}`);
  if (m && !fresh) issues.push('Viste quotes er eldre enn tre minutter. Ingen nye fills skal tolkes fra dem.');
  if (m?.unavailableVenues.length) issues.push('Noen pool-quotes mangler. Bare ruter med vellykkede svar vises.');
  if (m?.fx.label.startsWith('ANTATT')) issues.push(`USD/NOK ${m.fx.rate} er en antatt reservekurs fordi valutakilden ikke svarte.`);
  if (flashMessage) issues.push(flashMessage);
  alertMessage(issues.join(' '));
  if (latest) $('current-decision').innerHTML = `<span class="decision-indicator">◎</span><div><strong>${safe(latest.action)}</strong><p>${safe(latest.reason)}</p></div>`;
  $('timeline').innerHTML = state.decisions.length ? state.decisions.slice(1, 12).map(d => `<div class="timeline-item"><div class="timeline-head"><span>${safe(d.action)}</span><time>${safe(time(d.at))}</time></div><p>${safe(d.reason)}</p></div>`).join('') || '<p class="empty-note">Neste beslutning kommer ved neste markedsskanning.</p>' : '<p class="empty-note">Beslutninger vises her. Å vente er også en beslutning.</p>';
  $('routes').innerHTML = m ? m.candidates.slice(0, 6).map(r => `<tr><td class="route-name">${safe(r.route)}<small>USDC → WETH → USDC</small></td><td>${integer.format(r.amount)}</td><td class="${r.netNok > 0 ? 'positive' : 'negative'}">${money(r.netNok)}</td><td><span class="tag ${r.netNok >= state.assumptions.minNetNok + r.gasNok * state.assumptions.reserveMargin ? 'good' : ''}">${r.netNok >= state.assumptions.minNetNok + r.gasNok * state.assumptions.reserveMargin ? 'VURDERES' : 'VENT'}</span></td></tr>`).join('') : '<tr><td colspan="4" class="empty-cell">Ingen mainnet-quotes hentet ennå.</td></tr>';
  $('trades-body').innerHTML = state.trades.length ? state.trades.slice(0, 40).map(t => `<tr><td>${safe(time(t.at))}</td><td class="route-name">${safe(t.route)}<small>SIMULERT · blokk ${integer.format(t.block)}</small></td><td>${integer.format(t.amount)}</td><td>${money(t.gasNok)}</td><td>${money(t.builderNok)}</td><td class="${t.netNok >= 0 ? 'positive' : 'negative'}">${money(t.netNok)}</td><td><span class="tag ${t.outcome === 'revert' ? 'bad' : 'good'}">${t.outcome === 'revert' ? 'REVERT (MODELL)' : 'PAPER-FILL'}</span></td></tr>`).join('') : '<tr><td colspan="7" class="empty-cell">Ingen paperhandler. Å vente når kostnadene spiser opp spreaden er riktig oppførsel.</td></tr>';
  $('fx-note').textContent = m ? `${m.fx.label}: ${m.fx.rate} NOK/USD${m.fx.date ? ` · ${m.fx.date}` : ''}. ${m.fx.source}.` : 'Valutakurs: ikke hentet ennå.';
  $('owner').innerHTML = token ? 'Eierpassord angitt <span>✓</span>' : 'Eiertilgang <span>↗</span>';
  drawChart();
}
function drawChart() {
  const points = state.history.filter(p => Number.isFinite(p[chartMode]));
  if (!points.length) return;
  const W = 680, H = 210, L = 18, R = 22, T = 16, B = 29;
  const values = points.map(p => p[chartMode]); const low = Math.min(...values), high = Math.max(...values);
  const pad = Math.max((high - low) * .25, chartMode === 'equity' ? 3 : high * .001);
  const min = low - pad, max = high + pad;
  const xy = points.map((p, i) => [L + (W - L - R) * i / Math.max(points.length - 1, 1), T + (H - T - B) * (1 - (p[chartMode] - min) / (max - min))]);
  const line = xy.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(2)},${y.toFixed(2)}`).join(' ');
  const last = xy.at(-1); const grid = [0, 1, 2, 3].map(i => { const y = T + (H - T - B) * i / 3; return `<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="#2b2e3a" stroke-dasharray="3 5"/><text x="${W - R}" y="${y - 5}" text-anchor="end" fill="#636d84" font-size="8">${safe(integer.format(max - (max - min) * i / 3))}</text>`; }).join('');
  $('chart').innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${chartMode === 'equity' ? 'Simulert egenkapital basert på observerte tidspunkter' : 'Målt ETH-pris'}"><defs><linearGradient id="shade" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#b69bff" stop-opacity=".14"/><stop offset="1" stop-color="#b69bff" stop-opacity="0"/></linearGradient></defs>${grid}<path d="${line} L${last[0]},${H - B} L${L},${H - B} Z" fill="url(#shade)"/><path d="${line}" fill="none" stroke="#bb9bf4" stroke-width="2"/><circle cx="${last[0]}" cy="${last[1]}" r="3" fill="#d4baff"/><text x="${L}" y="${H - 6}" fill="#6c7690" font-size="9">${safe(time(points[0].at))}</text><text x="${W - R}" y="${H - 6}" text-anchor="end" fill="#6c7690" font-size="9">${safe(time(points.at(-1).at))}</text></svg>`;
}
$('owner').addEventListener('click', () => $('owner-dialog').showModal());
$('close-dialog').addEventListener('click', () => $('owner-dialog').close());
$('owner-form').addEventListener('submit', e => { e.preventDefault(); token = $('owner-token').value; $('owner-token').value = ''; $('owner-dialog').close(); if (state) render(); });
$('toggle').addEventListener('click', () => act(state?.running ? 'pause' : 'start'));
$('scan').addEventListener('click', () => act('scan'));
$('channel').addEventListener('change', e => { const channel = e.target.value; if (!token) e.target.value = state.channel; act('channel', { channel }); });
for (const button of document.querySelectorAll('[data-chart]')) button.addEventListener('click', () => { chartMode = button.dataset.chart; for (const b of document.querySelectorAll('[data-chart]')) b.classList.toggle('selected', b === button); if (state) render(); });
$('export').addEventListener('click', () => {
  if (!state?.trades.length) { alertMessage('Det finnes ingen paperhandler å eksportere ennå.'); return; }
  const cols = ['at', 'block', 'route', 'amount', 'gasNok', 'builderNok', 'netNok', 'outcome', 'label'];
  const csv = [cols.join(','), ...state.trades.map(t => cols.map(k => '"' + String(t[k] ?? '').replace(/"/g, '""') + '"').join(','))].join('\r\n');
  const url = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })); const a = document.createElement('a'); a.href = url; a.download = 'jarvis-paper-trades.csv'; a.click(); URL.revokeObjectURL(url);
});
refresh(); setInterval(refresh, 15000);
