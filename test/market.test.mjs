// Synthetic JSON-RPC fixtures only: no market results or example dashboard curves are generated.
import test from 'node:test';
import assert from 'node:assert/strict';
import { scanMarket, USDC, VENUES, evaluate, MODEL } from '../server/market.mjs';
import { getRPCURL, RPC, word, dataWords } from '../server/rpc.mjs';
const now = Date.parse('2026-10-18T12:00:00Z'), block = 24_000_000;
function encoded(...values) { return '0x' + values.map(word).join(''); }
function fixture() {
  const seen = [];
  const fetcher = async (url, options) => {
    if (url.includes('frankfurter')) return Response.json({ rates: { NOK: 10.5 }, date: '2026-10-16' });
    const { method, params } = JSON.parse(options.body); seen.push({ method, params }); let result;
    if (method === 'eth_chainId') result = '0x1';
    else if (method === 'eth_getBlockByNumber') result = { number: '0x' + block.toString(16), timestamp: '0x' + Math.floor(now / 1000).toString(16), baseFeePerGas: '0x3b9aca00', hash: '0xfixture' };
    else if (method === 'eth_feeHistory') result = { reward: [['0x5f5e100']] };
    else if (method === 'eth_call') {
      const { to, data } = params[0], selector = data.slice(0, 10);
      if (selector === '0xfeaf968c') result = encoded(1, to.toLowerCase().startsWith('0x5f4e') ? 3000 * 1e8 : 1e8, now / 1000, now / 1000, 1);
      else if (selector === '0x026b1d5f') result = encoded(100);
      else if (selector === '0x074b2e43') result = encoded(5);
      else {
        const w = dataWords('0x' + data.slice(10)); const isV2 = selector === '0xd06ca61f'; const amount = w[isV2 ? 0 : 2];
        const input = '0x' + w[isV2 ? 3 : 0].toString(16).padStart(40, '0'); const usdcIn = input.toLowerCase() === USDC.toLowerCase();
        const i = isV2 ? VENUES.findIndex(v => v.target.toLowerCase() === to.toLowerCase()) : w[3] === 500n ? 2 : 3;
        const price = [3000, 3150, 3030, 3100][i]; const reserveUsd = BigInt(price) * 10000n * 1000000n, reserveEth = 10000n * 10n ** 18n;
        const rin = usdcIn ? reserveUsd : reserveEth, rout = usdcIn ? reserveEth : reserveUsd;
        const fee = isV2 ? 3000n : w[3]; const adjusted = amount * (1000000n - fee); const out = adjusted * rout / (rin * 1000000n + adjusted);
        result = isV2 ? encoded(32, 2, amount, out) : encoded(out, 1, 0, 100000);
      }
    } else throw Error('Unexpected mock method');
    return Response.json({ jsonrpc: '2.0', id: 1, result });
  };
  return { seen, fetcher };
}
test('real scanner path uses one pinned block, 36 route/size quotes and explicit cost model', async () => {
  const { seen, fetcher } = fixture(); const m = await scanMarket({ env: { ALCHEMY_API_KEY: 'synthetic-key' }, fetcher, now });
  assert.equal(m.candidates.length, 36); assert.equal(m.ethUsd, 3000); assert.equal(m.premiumBps, 5); assert.equal(m.fx.rate, 10.5);
  assert.ok(m.candidates[0].netNok > m.candidates.at(-1).netNok);
  assert.ok(seen.filter(x => x.method === 'eth_call').every(x => x.params[1] === '0x' + block.toString(16)));
  assert.equal(m.model.gasUnits, 450000); assert.equal(m.fx.label, 'MÅLT dagskurs');
});
test('scanner rejects a non-mainnet provider', async () => {
  const fetcher = async () => Response.json({ result: '0xaa36a7' }); await assert.rejects(scanMarket({ env: { ALCHEMY_API_KEY: 'synthetic' }, fetcher, now }), /ikke Ethereum mainnet/);
});
test('RPC blocks transaction sending and redacts upstream secrets', async () => {
  const rpc = new RPC('https://example.invalid/SECRET', async () => Response.json({ error: { code: -32000, message: 'SECRET https://example.invalid/SECRET' } }));
  await assert.rejects(rpc.request('eth_sendRawTransaction'), /Kun lesing/);
  await assert.rejects(rpc.request('eth_call'), e => !e.message.includes('SECRET'));
});
test('separate server credentials or full URL work without publishing them', () => {
  assert.equal(getRPCURL({ ALCHEMY_API_KEY: 'synthetic' }), 'https://eth-mainnet.g.alchemy.com/v2/synthetic');
  assert.equal(getRPCURL({ ETH_RPC_URL: 'https://example.invalid/rpc' }), 'https://example.invalid/rpc');
  assert.throws(() => getRPCURL({})); assert.throws(() => getRPCURL({ ETH_RPC_URL: 'http://example.invalid' }));
});
test('costs include flash premium, gas, builder and separate adverse buffer', () => {
  const r = evaluate({ amount: 10000, result: 10100n * 1000000n, ethUsd: 3000, gasWei: 1000000000n, premiumBps: 5, fx: 10 });
  assert.equal(r.grossUsd, 100); assert.equal(r.premiumUsd, 5); assert.ok(Math.abs(r.gasUsd - 1.35) < 1e-10); assert.equal(r.bufferUsd, 3);
  assert.ok(Math.abs(r.netUsd - (100 - 5 - 1.35 - 93.65 * .9 - 3)) < 1e-10);
});
