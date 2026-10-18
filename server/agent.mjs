import { createHash } from 'node:crypto';
import { MODEL } from './market.mjs';
export const START_NOK = 5000;
export function initialState(now = Date.now()) {
  return { schema: 1, createdAt: new Date(now).toISOString(), updatedAt: null, running: false, channel: 'private', balance: START_NOK, peak: START_NOK, maxDrawdown: 0, market: null, pending: null, history: [], trades: [], decisions: [], losses: [], failures: [], counters: { scans: 0, opportunities: 0, wins: 0, failed: 0, missed: 0, competition: 0, gasNok: 0, builderNok: 0 }, lease: null, lastError: null, lastScanAt: 0 };
}
export function log(state, action, reason, now) {
  state.decisions = [{ at: new Date(now).toISOString(), action, reason: String(reason).slice(0, 500) }, ...state.decisions].slice(0, 120);
}
function weekStart(now) { const d = new Date(now); d.setUTCHours(0, 0, 0, 0); d.setUTCDate(d.getUTCDate() - (d.getUTCDay() + 6) % 7); return d.getTime(); }
export function riskReason(state, candidate, market, now) {
  const daily = state.losses.filter(x => x.at >= new Date(now).setUTCHours(0, 0, 0, 0)).reduce((s, x) => s + x.nok, 0);
  const weekly = state.losses.filter(x => x.at >= weekStart(now)).reduce((s, x) => s + x.nok, 0);
  const exposure = Math.max(candidate.gasNok, candidate.revertGasNok);
  if (daily + exposure > MODEL.maxDailyLossNok) return 'Daglig tapssperre: agenten venter til neste UTC-dag.';
  if (weekly + exposure > MODEL.maxWeeklyLossNok) return 'Ukentlig tapssperre: agenten venter til neste UTC-uke.';
  if (state.failures.filter(at => at > now - 3600000).length >= MODEL.maxFailuresHour) return 'For mange simulerte feil siste time.';
  if (candidate.gasNok > MODEL.maxGasNok || market.gasGwei > MODEL.maxGasGwei) return 'Gasskostnaden er over budsjettet.';
  const min = MODEL.minNetNok + candidate.gasNok * MODEL.reserveMargin;
  if (candidate.netNok < min) return `For lav netto etter kostnader og sikkerhetsmargin (krav ${min.toFixed(2)} NOK).`;
  if (state.balance < Math.max(candidate.gasNok + candidate.builderUsd * market.fx.rate, candidate.revertGasNok)) return 'Den virtuelle gass-lommeboken har for lite kapital.';
  return null;
}
export function randomValue(key) { return createHash('sha256').update(key).digest().readUInt32BE() / 2 ** 32; }
function recordTrade(state, pending, c, market, outcome, now) {
  const failed = outcome === 'revert'; const net = Math.round((failed ? -c.revertGasNok : c.netNok) * 100) / 100;
  state.balance = Math.round((state.balance + net) * 100) / 100;
  if (net < 0) state.losses.push({ at: now, nok: -net });
  if (failed) { state.failures.push(now); state.counters.failed++; } else { state.counters.wins++; }
  state.counters.gasNok += failed ? c.revertGasNok : c.gasNok;
  state.counters.builderNok += failed ? 0 : c.builderUsd * market.fx.rate;
  state.trades = [{ at: new Date(now).toISOString(), block: market.block, signalBlock: pending.block, route: c.route, amount: c.amount, netNok: net, gasNok: failed ? c.revertGasNok : c.gasNok, builderNok: failed ? 0 : c.builderUsd * market.fx.rate, premiumUsd: failed ? 0 : c.premiumUsd, bufferUsd: failed ? 0 : c.bufferUsd, fx: market.fx, outcome, label: 'SIMULERT UTFALL — ikke EVM-verifisert', id: `${pending.block}:${c.id}` }, ...state.trades].slice(0, 300);
  log(state, failed ? 'SIMULERT REVERT' : 'PAPERHANDEL', failed ? `Offentlig modellforsøk reverterte: −${c.revertGasNok.toFixed(2)} NOK i antatt gass.` : `Antatt inklusjon og fill: ${c.route}, ${net.toFixed(2)} NOK etter modellerte kostnader.`, now);
}
export async function chooseCandidate(candidates, market, { env = process.env, fetcher = fetch } = {}) {
  if (!env.OPENAI_API_KEY) return { id: candidates[0]?.id ?? null, engine: 'rules', reason: 'Regelagent: høyest beregnet netto blant ruter som passerer risikogrenser.' };
  try {
    const res = await fetcher('https://api.openai.com/v1/chat/completions', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${env.OPENAI_API_KEY}` }, signal: AbortSignal.timeout(8000), body: JSON.stringify({ model: env.OPENAI_MODEL || 'gpt-4.1-mini', max_completion_tokens: 220, response_format: { type: 'json_object' }, messages: [
      { role: 'system', content: 'You decide PAPER trades only, never real trades. Candidates have passed hard risk limits. Return JSON {"id": one exact candidate id or null to WAIT, "reason": concise Norwegian explanation}. Select only supplied IDs. Quotes and costs are not executable guarantees. Prefer waiting when uncertainty is high. Do not invent facts or change amounts.' },
      { role: 'user', content: JSON.stringify({ block: market.block, measurement: 'mainnet quotes at one observed block; no EVM simulation', captureProbabilityAssumed: MODEL.captureProbability, candidates: candidates.slice(0, 3).map(c => ({ id: c.id, route: c.route, amountUSDC: c.amount, netNok: c.netNok, gasNok: c.gasNok })) }) },
    ] }) });
    if (!res.ok) throw Error(); const data = await res.json(); const decision = JSON.parse(data.choices[0].message.content);
    if (decision.id !== null && !candidates.some(c => c.id === decision.id)) throw Error();
    return { id: decision.id, engine: 'openai', reason: String(decision.reason ?? 'AI valgte å vente.').slice(0, 400) };
  } catch { return { id: null, engine: 'openai', reason: 'AI-tjenesten kunne ikke gi en gyldig beslutning. Ingen paperhandel åpnes.' }; }
}
export async function advance(state, market, { now = Date.now(), compete = async () => ({ unknown: true }), choose = chooseCandidate, random = randomValue, env = process.env, fetcher = fetch } = {}) {
  // Idempotent across browser polls and scheduled invocations; never replay an observed block.
  if (state.market && market.block <= state.market.block) return state;
  state.market = market; state.updatedAt = new Date(now).toISOString(); state.lastError = null; state.counters.scans++;
  state.losses = state.losses.filter(x => x.at >= now - 8 * 86400000); state.failures = state.failures.filter(at => at > now - 3600000);
  let settled = false;
  if (!state.running) { state.pending = null; log(state, 'OBSERVERER', 'Nye mainnet-quotes hentet. Agenten er pauset; ingen nye paperforsøk.', now); }
  else if (state.pending) {
    const p = state.pending; const candidate = market.candidates.find(c => c.id === p.id); state.pending = null; settled = true;
    let competition; try { competition = await compete(p, market, { env, fetcher }); } catch { competition = { unknown: true }; }
    // Evaluate ONLY the previously chosen route, never cherry-pick the next observation's winner.
    const reason = candidate ? riskReason(state, candidate, market, now) : 'Ruten kunne ikke prises på nytt.';
    const tooOld = now - p.at > 180000 || market.block - p.block > 100;
    if (tooOld || competition.unknown) { state.counters.missed++; log(state, 'DROPPET', 'Utdatert signal eller ukjente konkurransedata. Ingen hypotetisk fill bokføres.', now); }
    else if (competition.matched) {
      state.counters.competition++;
      if (state.channel === 'public' && candidate && !reason) recordTrade(state, p, candidate, market, 'revert', now);
      else { state.counters.missed++; log(state, 'TAPT KONKURRANSE', 'Swap-events viser begge rutelegg i samme transaksjon. Konservativ konkurranseproxy; ingen privat fill.', now); }
    } else if (reason) { state.counters.missed++; log(state, 'DROPPET', `${reason} Forrige signal er ikke bokført som gevinst.`, now); }
    else if (random(`${p.block}:${p.id}:capture`) >= MODEL.captureProbability) { state.counters.missed++; log(state, 'IKKE INKLUDERT', 'Modellert konkurranse: forsøket fikk ingen inklusjon. Ingen gass belastes.', now); }
    else {
      const failed = state.channel === 'public' && random(`${p.block}:${p.id}:failure`) < MODEL.publicFailureProbability;
      recordTrade(state, p, candidate, market, failed ? 'revert' : 'paper-fill', now);
    }
  }
  if (state.running && !settled) {
    const eligible = market.candidates.filter(c => !riskReason(state, c, market, now));
    if (!eligible.length) {
      log(state, 'VENTER', market.candidates[0] ? riskReason(state, market.candidates[0], market, now) : 'Ingen målbare ruter tilgjengelig.', now);
    } else {
      state.counters.opportunities++;
      const decision = await choose(eligible, market, { env, fetcher });
      const c = eligible.find(x => x.id === decision.id);
      if (!c) log(state, 'AI VENTER', decision.reason, now);
      else {
        state.pending = { id: c.id, block: market.block, first: c.first, second: c.second, amount: c.amount, at: now, expectedNetNok: c.netNok, engine: decision.engine };
        log(state, 'SIGNAL', `${decision.reason} Avventer neste måling før et simulert utfall.`, now);
      }
    }
  }
  state.peak = Math.max(state.peak, state.balance); state.maxDrawdown = Math.max(state.maxDrawdown, (state.peak - state.balance) / state.peak);
  state.history = [...state.history, { at: new Date(now).toISOString(), block: market.block, equity: state.balance, ethUsd: market.ethUsd, bestNetNok: market.candidates[0]?.netNok ?? null }].slice(-1440);
  return state;
}
