import { RPC, getRPCURL, quoteData, addressWord } from './rpc.mjs';
export const USDC = '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48';
export const WETH = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2';
const QUOTER = '0x61fFE014bA17989E743c5F6cB21bF9697530B21e';
export const VENUES = [
  { id: 'uni-v2', name: 'Uniswap V2', fee: 3000, kind: 'v2', target: '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D' },
  { id: 'sushi-v2', name: 'SushiSwap V2', fee: 3000, kind: 'v2', target: '0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F' },
  { id: 'uni-v3-500', name: 'Uniswap V3 · 0,05 %', fee: 500, kind: 'v3', target: QUOTER },
  { id: 'uni-v3-3000', name: 'Uniswap V3 · 0,30 %', fee: 3000, kind: 'v3', target: QUOTER },
];
export const MODEL = Object.freeze({ amounts: [1000, 10000, 50000], gasUnits: 450000, revertGasUnits: 200000, builderShare: .90, executionBufferBps: 3, captureProbability: .10, publicFailureProbability: .20, minNetNok: 2, maxGasNok: 30, maxGasGwei: 100, maxDailyLossNok: 50, maxWeeklyLossNok: 150, maxFailuresHour: 3, reserveMargin: .25 });
async function quote(rpc, venue, input, output, amount, block) {
  const w = await rpc.call(venue.target, quoteData(venue, input, output, amount), block);
  if (venue.kind === 'v3') { if (!w.length) throw Error('V3 quote mangler'); return w[0]; }
  const offset = Number(w[0] / 32n); if (w[offset] !== 2n || w.length <= offset + 2) throw Error('V2 quote mangler'); return w[offset + 2];
}
export function evaluate({ amount, result, ethUsd, gasWei, premiumBps, fx, usdcUsd = 1, model = MODEL }) {
  const gross = (Number(result) / 1e6 - amount) * usdcUsd;
  const premium = Math.floor((amount * 1e6 * premiumBps + 5000) / 10000) / 1e6 * usdcUsd;
  const gas = model.gasUnits * Number(gasWei) / 1e18 * ethUsd;
  const builder = Math.max(0, gross - premium - gas) * model.builderShare;
  const buffer = amount * usdcUsd * model.executionBufferBps / 10000;
  const netUsd = gross - premium - gas - builder - buffer;
  if (![gross, premium, gas, builder, buffer, netUsd, fx].every(Number.isFinite)) throw Error('Ugyldige tall i kostnadsmodellen.');
  return { grossUsd: gross, premiumUsd: premium, gasUsd: gas, builderUsd: builder, bufferUsd: buffer, netUsd, netNok: netUsd * fx, gasNok: gas * fx, revertGasNok: model.revertGasUnits * Number(gasWei) / 1e18 * ethUsd * fx };
}
let fxCache;
export async function fxRate(fetcher = fetch, now = Date.now()) {
  if (fxCache && now - fxCache.at < 3600000) return fxCache.value;
  try {
    const r = await fetcher('https://api.frankfurter.dev/v1/latest?base=USD&symbols=NOK', { signal: AbortSignal.timeout(3500) });
    if (!r.ok) throw Error(); const data = await r.json(); const rate = Number(data.rates?.NOK);
    if (!(rate > 1 && rate < 30) || !/^\d{4}-\d{2}-\d{2}$/.test(data.date) || now - Date.parse(data.date) > 7 * 86400000 || Date.parse(data.date) > now) throw Error();
    const value = { rate, date: data.date, source: 'ECB via Frankfurter', label: 'MÅLT dagskurs' }; fxCache = { at: now, value }; return value;
  } catch { return { rate: 10.5, date: null, source: 'Reserveantakelse, FX-tjenesten svarte ikke', label: 'ANTATT USD/NOK' }; }
}
export async function scanMarket({ env = process.env, fetcher = fetch, now = Date.now() } = {}) {
  const rpc = new RPC(getRPCURL(env), fetcher);
  if (BigInt(await rpc.request('eth_chainId')) !== 1n) throw Error('Endpointet er ikke Ethereum mainnet.');
  const raw = await rpc.request('eth_getBlockByNumber', ['latest', false]);
  const block = Number(BigInt(raw.number)), timestamp = Number(BigInt(raw.timestamp)) * 1000;
  if (now - timestamp > 180000 || timestamp > now + 30000) throw Error('RPC-blokken er foreldet. Agenten venter.');
  const fxPromise = fxRate(fetcher, now);
  const ethW = await rpc.call('0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419', '0xfeaf968c', block);
  if (ethW.length < 5 || ethW[1] <= 0n || ethW[1] >= 2n ** 255n || ethW[4] < ethW[0] || now / 1000 - Number(ethW[3]) > 86400 || Number(ethW[3]) * 1000 > now) throw Error('ETH/USD-orakelet er foreldet eller ugyldig.');
  const ethUsd = Number(ethW[1]) / 1e8;
  // USDC depeg is priced from Chainlink; do not silently equate a token with USD.
  const usdW = await rpc.call('0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6', '0xfeaf968c', block);
  if (usdW.length < 5 || usdW[1] <= 0n || usdW[1] >= 2n ** 255n || usdW[4] < usdW[0] || now / 1000 - Number(usdW[3]) > 86400 || Number(usdW[3]) * 1000 > now) throw Error('USDC/USD-orakelet er foreldet eller ugyldig.');
  const usdcUsd = Number(usdW[1]) / 1e8;
  const providerW = await rpc.call('0x2f39d218133AFaB8F2B819B1066c7E434Ad94E9e', '0x026b1d5f', block);
  const pool = '0x' + providerW[0].toString(16).padStart(40, '0');
  const premiumBps = Number((await rpc.call(pool, '0x074b2e43', block))[0]);
  let tipWei, tipSource;
  try { const h = await rpc.request('eth_feeHistory', ['0x1', raw.number, [50]]); tipWei = BigInt(h.reward[0][0]); tipSource = 'MÅLT median i observert blokk'; }
  catch { tipWei = BigInt(await rpc.request('eth_maxPriorityFeePerGas')); tipSource = 'ANTATT bud fra RPC-anbefaling'; }
  if (tipWei < 0n || !Number.isFinite(ethUsd) || !Number.isFinite(usdcUsd) || !Number.isInteger(premiumBps) || premiumBps < 0 || premiumBps > 10000) throw Error('Ugyldige pris- eller gebyrdata.');
  const gasWei = BigInt(raw.baseFeePerGas) * 1125n / 1000n + tipWei; const fx = await fxPromise;
  const errors = new Set(); const candidates = [];
  for (const amount of MODEL.amounts) {
    const buys = await Promise.all(VENUES.map(async venue => {
      try { return { venue, out: await quote(rpc, venue, USDC, WETH, BigInt(amount) * 1000000n, block) }; }
      catch { errors.add(venue.id); return null; }
    }));
    const routes = buys.flatMap(buy => buy ? VENUES.filter(v => v.id !== buy.venue.id).map(async sell => {
      try {
        const out = await quote(rpc, sell, WETH, USDC, buy.out, block);
        // USDC principal/premium are rounded in token units before USD valuation.
        const values = evaluate({ amount, result: out, usdcUsd, ethUsd, gasWei, premiumBps, fx: fx.rate });
        return { id: `${buy.venue.id}:${sell.id}:${amount}`, amount, first: buy.venue.id, second: sell.id, route: `${buy.venue.name} → ${sell.name}`, ...values };
      } catch { errors.add(sell.id); return null; }
    }) : []);
    candidates.push(...(await Promise.all(routes)).filter(Boolean));
  }
  if (!candidates.length) throw Error('Ingen gyldige pool-quotes. Ingen paperhandel bokføres.');
  candidates.sort((a, b) => b.netNok - a.netNok);
  return { block, blockHash: raw.hash, timestamp: new Date(timestamp).toISOString(), observedAt: new Date(now).toISOString(), ethUsd, usdcUsd, fx, premiumBps, baseGwei: Number(BigInt(raw.baseFeePerGas)) / 1e9, gasGwei: Number(gasWei) / 1e9, tipGwei: Number(tipWei) / 1e9, tipSource, candidates, unavailableVenues: [...errors], model: MODEL, rpcCalls: rpc.count };
}
const factories = ['0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f', '0xC0AEe478e3658e2610c5F7A4A2E1777cE9e4f2Ac', '0x1F98431c8aD98523631AE4a59f267346ea31F984', '0x1F98431c8aD98523631AE4a59f267346ea31F984'];
const SWAP2 = '0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822';
const SWAP3 = '0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67';
export async function competingSwaps(pending, market, { env = process.env, fetcher = fetch } = {}) {
  if (market.block - pending.block > 100) return { unknown: true, matched: false };
  const rpc = new RPC(getRPCURL(env), fetcher); const indices = [pending.first, pending.second].map(id => VENUES.findIndex(v => v.id === id));
  const pools = await Promise.all(indices.map(async i => {
    const v = VENUES[i]; const data = i < 2 ? '0xe6a43905' + addressWord(USDC) + addressWord(WETH) : '0x1698ee82' + addressWord(USDC) + addressWord(WETH) + BigInt(v.fee).toString(16).padStart(64, '0');
    return '0x' + (await rpc.call(factories[i], data, pending.block))[0].toString(16).padStart(40, '0');
  }));
  const logs = await rpc.request('eth_getLogs', [{ fromBlock: '0x' + (pending.block + 1).toString(16), toBlock: '0x' + market.block.toString(16), address: pools, topics: [[SWAP2, SWAP3]] }]);
  const buys = new Set(), sells = new Set();
  for (const l of logs) {
    const data = l.data.slice(2).match(/.{64}/g)?.map(w => BigInt('0x' + w)); if (!data || data.length < 2) throw Error('Ugyldige swap-events.');
    const first = l.address.toLowerCase() === pools[0].toLowerCase();
    const usdcIn = l.topics[0].toLowerCase() === SWAP2 ? data[0] > 0n && data[2] === 0n : data[0] > 0n && data[0] < 2n ** 255n;
    // All canonical pools here sort USDC (0xa0...) before WETH (0xc0...).
    if (first && usdcIn) buys.add(l.transactionHash); if (!first && !usdcIn) sells.add(l.transactionHash);
  }
  return { matched: [...buys].some(tx => sells.has(tx)), unknown: false, transactions: logs.length };
}
