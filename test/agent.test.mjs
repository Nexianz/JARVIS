import test from 'node:test';
import assert from 'node:assert/strict';
import { initialState, advance, riskReason, chooseCandidate } from '../server/agent.mjs';
import { handle } from '../server/api.mjs';
import { tick, command, publicState, authorized, KEY } from '../server/service.mjs';
const now = Date.parse('2026-10-18T12:00:00Z');
export function market(block = 100) {
  return { block, observedAt: new Date(now).toISOString(), ethUsd: 3000, fx: { rate: 10, label: 'MÅLT test-fixture' }, gasGwei: 2, candidates: [{ id: 'a:b:1000', amount: 1000, first: 'a', second: 'b', route: 'Pool A → B', netNok: 25, gasNok: 2, revertGasNok: 1, builderUsd: .5, premiumUsd: .5, bufferUsd: .3 }] };
}
const noCompetition = async () => ({ matched: false, unknown: false });
const options = { now, compete: noCompetition, random: () => 0, env: {} };
test('signal requires later observation; same block cannot book profit', async () => {
  const s = initialState(now); s.running = true; await advance(s, market(), options); assert.ok(s.pending); assert.equal(s.balance, 5000);
  await advance(s, market(), { ...options, now: now + 60000 }); assert.equal(s.counters.scans, 1); assert.equal(s.balance, 5000);
  await advance(s, market(105), { ...options, now: now + 60000 }); assert.equal(s.balance, 5025); assert.equal(s.counters.wins, 1); assert.match(s.trades[0].label, /SIMULERT/);
});
test('negative route produces WAIT and no imaginary gains', async () => {
  const s = initialState(now); s.running = true; const m = market(); m.candidates[0].netNok = -5;
  await advance(s, m, options); assert.equal(s.pending, null); assert.equal(s.balance, 5000); assert.equal(s.decisions[0].action, 'VENTER');
});
test('private competition loses without gas charge', async () => {
  const s = initialState(now); s.running = true; await advance(s, market(), options);
  await advance(s, market(105), { ...options, now: now + 60000, compete: async () => ({ matched: true }) });
  assert.equal(s.counters.competition, 1); assert.equal(s.balance, 5000); assert.equal(s.trades.length, 0);
});
test('public competition causes a modeled revert cost', async () => {
  const s = initialState(now); s.running = true; s.channel = 'public'; await advance(s, market(), options);
  await advance(s, market(105), { ...options, now: now + 60000, compete: async () => ({ matched: true }) });
  assert.equal(s.balance, 4999); assert.equal(s.counters.failed, 1); assert.equal(s.counters.builderNok, 0);
});
test('unknown competition does not silently count a win', async () => {
  const s = initialState(now); s.running = true; await advance(s, market(), options);
  await advance(s, market(105), { ...options, now: now + 60000, compete: async () => { throw Error(); } }); assert.equal(s.balance, 5000); assert.equal(s.counters.missed, 1);
});
test('modeled non-inclusion does not charge gas', async () => {
  const s = initialState(now); s.running = true; await advance(s, market(), options);
  await advance(s, market(105), { ...options, now: now + 60000, random: () => .99 }); assert.equal(s.balance, 5000); assert.equal(s.counters.missed, 1);
});
test('cannot replace pending route with a future winning route', async () => {
  const s = initialState(now); s.running = true; await advance(s, market(), options); const next = market(105); next.candidates[0].id = 'future-winner';
  await advance(s, next, { ...options, now: now + 60000 }); assert.equal(s.trades.length, 0); assert.equal(s.pending, null);
});
test('daily and weekly kill switches reserve worst-case loss', () => {
  const s = initialState(now), m = market(), c = m.candidates[0];
  s.losses = [{ at: now - 1000, nok: 49 }]; assert.match(riskReason(s, c, m, now), /Daglig/);
  s.losses = [{ at: now - 86400000, nok: 149 }]; assert.match(riskReason(s, c, m, now), /Ukentlig/);
});
test('hourly failure cap expires and gas cap blocks', () => {
  const s = initialState(now), m = market(), c = m.candidates[0]; s.failures = [now, now, now];
  assert.match(riskReason(s, c, m, now), /siste time/); assert.equal(riskReason(s, c, m, now + 3600001), null);
  c.gasNok = 31; assert.match(riskReason(s, c, m, now + 3600001), /Gass/);
});
test('AI cannot choose a nonexistent candidate or bypass limits', async () => {
  const m = market(); const response = await chooseCandidate(m.candidates, m, { env: { OPENAI_API_KEY: 'synthetic' }, fetcher: async () => Response.json({ choices: [{ message: { content: '{"id":"made-up","reason":"invented"}' } }] }) });
  assert.equal(response.id, null); assert.equal(response.engine, 'openai');
});
test('valid AI decision chooses only a prevalidated ID', async () => {
  const m = market(); const response = await chooseCandidate(m.candidates, m, { env: { OPENAI_API_KEY: 'synthetic' }, fetcher: async () => Response.json({ choices: [{ message: { content: JSON.stringify({ id: m.candidates[0].id, reason: 'Sjekket risiko.' }) } }] }) }); assert.equal(response.id, m.candidates[0].id);
});
export class MemoryStore {
  value = null; revision = 0;
  async getWithMetadata() { return this.value ? { data: structuredClone(this.value), etag: String(this.revision) } : null; }
  async setJSON(key, value, opts) {
    if (opts.onlyIfNew && this.value || opts.onlyIfMatch && opts.onlyIfMatch !== String(this.revision)) return { modified: false };
    this.value = structuredClone(value); this.revision++; return { modified: true, etag: String(this.revision) };
  }
}
const env = { PAPER_ADMIN_TOKEN: 'synthetic-owner-password', ALCHEMY_API_KEY: 'synthetic-rpc-key' };
test('concurrent ticks use CAS so one scan runs', async () => {
  const store = new MemoryStore(); await command(store, 'start', null, { env, now }); let calls = 0;
  await Promise.all([1, 2].map(() => tick(store, { env, now, scan: async () => { calls++; await new Promise(r => setTimeout(r, 5)); return market(); }, compete: noCompetition })));
  assert.equal(calls, 1); assert.equal(store.value.counters.scans, 1); assert.equal(store.value.lease, null);
});
test('paused scheduled agent uses no market requests', async () => {
  const store = new MemoryStore(); let scanned = false; await tick(store, { now, scan: async () => { scanned = true; } }); assert.equal(scanned, false);
});
test('owner password required; examples are rejected', () => {
  const req = new Request('https://example.invalid', { headers: { Authorization: 'Bearer REPLACE_WITH_RANDOM_OWNER_PASSWORD' } });
  assert.equal(authorized(req, { PAPER_ADMIN_TOKEN: 'REPLACE_WITH_RANDOM_OWNER_PASSWORD' }), false); assert.equal(authorized(req, {}), false);
});
test('public API cannot start the agent or expose secrets', async () => {
  const store = new MemoryStore(); const req = new Request('https://example.invalid/api/agent', { method: 'POST', body: '{"action":"start"}' });
  assert.equal((await handle(req, store, { env })).status, 401); assert.equal(store.value, null);
  const response = await handle(new Request('https://example.invalid/api/agent'), store, { env }); const text = await response.text();
  assert.ok(!text.includes(env.ALCHEMY_API_KEY)); assert.ok(!text.includes(env.PAPER_ADMIN_TOKEN)); assert.equal(JSON.parse(text).balance, 5000);
});
test('owner can start and pause; pause cancels unspent pending signal', async () => {
  const store = new MemoryStore(); await command(store, 'start', null, { env, now }); assert.equal(store.value.running, true);
  await command(store, 'pause', null, { env, now: now + 1 }); assert.equal(store.value.running, false); assert.equal(store.value.pending, null);
});
test('cross-origin mutation is rejected even with owner token', async () => {
  const r = await handle(new Request('https://site.invalid/api/agent', { method: 'POST', headers: { authorization: `Bearer ${env.PAPER_ADMIN_TOKEN}`, origin: 'https://other.invalid' }, body: '{"action":"start"}' }), new MemoryStore(), { env }); assert.equal(r.status, 403);
});

test('missing storage version fails closed instead of overwriting another scan', async () => {
  const { load } = await import('../server/service.mjs');
  await assert.rejects(load({ getWithMetadata: async () => ({ data: initialState(now) }) }), /versjons-ID/);
});
