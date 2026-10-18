import { timingSafeEqual, randomUUID } from 'node:crypto';
import { initialState, advance, log } from './agent.mjs';
import { scanMarket, competingSwaps, MODEL } from './market.mjs';
export const KEY = 'paper-agent-v1';
export function authorized(request, env = process.env) {
  const expected = env.PAPER_ADMIN_TOKEN;
  if (!expected || expected.length < 16 || expected.includes('REPLACE')) return false;
  const actual = request.headers.get('authorization')?.replace(/^Bearer /, '') ?? '';
  const a = Buffer.from(actual), b = Buffer.from(expected); return a.length === b.length && timingSafeEqual(a, b);
}
export function capabilities(env = process.env) {
  return { rpcConfigured: Boolean(env.ETH_RPC_URL || env.ALCHEMY_API_KEY), adminConfigured: Boolean(env.PAPER_ADMIN_TOKEN && env.PAPER_ADMIN_TOKEN.length >= 16 && !env.PAPER_ADMIN_TOKEN.includes('REPLACE')), engine: env.OPENAI_API_KEY ? 'openai' : 'rules', model: env.OPENAI_API_KEY ? env.OPENAI_MODEL || 'gpt-4.1-mini' : null };
}
export async function load(store) {
  const record = await store.getWithMetadata(KEY, { type: 'json', consistency: 'strong' });
  if (record && !record.etag) throw Error('Lagringen mangler versjons-ID. Ingen endring er tillatt.');
  return record;
}
async function write(store, value, etag) { return store.setJSON(KEY, value, etag ? { onlyIfMatch: etag } : { onlyIfNew: true }); }
export async function publicState(store, env = process.env) {
  const record = await load(store); const state = record?.data ?? initialState();
  const { lease, losses, failures, ...safe } = state;
  return { ...safe, capabilities: capabilities(env), assumptions: MODEL, busy: Boolean(lease && lease.until > Date.now()), startNok: 5000 };
}
export async function command(store, action, channel, { env = process.env, now = Date.now() } = {}) {
  if (!['start', 'pause', 'channel'].includes(action)) throw Error('Ukjent handling.');
  const r = await load(store); const s = r?.data ?? initialState(now);
  if (s.lease?.until > now) return { conflict: true };
  if (action === 'start') { if (!capabilities(env).rpcConfigured) throw Error('Alchemy må konfigureres i Netlify først.'); s.running = true; log(s, 'STARTET', 'Paper-agent startet. Første markedsmåling kommer innen omtrent ett minutt.', now); }
  if (action === 'pause') { s.running = false; s.pending = null; log(s, 'PAUSET', 'Agenten er pauset. Ingen nye paperforsøk eller planlagte markedskall.', now); }
  if (action === 'channel') { if (!['public', 'private'].includes(channel)) throw Error('Ugyldig kanal.'); if (s.running) throw Error('Pause agenten før du endrer utførelsesmodell.'); s.channel = channel; s.pending = null; }
  s.updatedAt = new Date(now).toISOString();
  const result = await write(store, s, r?.etag); return { conflict: !result.modified };
}
export async function tick(store, { manual = false, env = process.env, now = Date.now(), scan = scanMarket, compete = competingSwaps, choose, random, fetcher = fetch } = {}) {
  const before = await load(store); const state = before?.data ?? initialState(now);
  if ((!state.running && !manual) || state.lease?.until > now || now - state.lastScanAt < 45000) return { skipped: true };
  const lease = { id: randomUUID(), until: now + 55000 }; state.lease = lease;
  const claimed = await write(store, state, before?.etag); if (!claimed.modified) return { skipped: true };
  const locked = await load(store); if (locked?.data.lease?.id !== lease.id) return { skipped: true };
  const next = locked.data; next.lastScanAt = now;
  const deadline = AbortSignal.timeout(35000);
  const boundedFetch = (url, opts = {}) => fetcher(url, { ...opts, signal: opts.signal ? AbortSignal.any([opts.signal, deadline]) : deadline });
  try { const market = await scan({ env, fetcher: boundedFetch, now }); await advance(next, market, { env, now, compete, choose, random, fetcher: boundedFetch }); }
  catch (error) {
    // Only own known messages escape; never serialize upstream exception bodies or URLs.
    const message = String(error.message ?? '').replace(/https?:\/\/[^\s]+/g, '[endpoint skjult]').replace(/alch_[\w-]+/g, '[nøkkel skjult]').slice(0, 240);
    next.lastError = message || 'Markedsskanningen feilet.'; log(next, 'DATAFEIL', next.lastError, now);
  }
  next.lease = null; next.updatedAt = new Date(now).toISOString();
  const saved = await write(store, next, locked.etag); return { skipped: false, saved: saved.modified };
}
