const word = n => BigInt(n).toString(16).padStart(64, '0');
export const addressWord = a => { if (!/^0x[\da-f]{40}$/i.test(a)) throw Error('Ugyldig adresse'); return a.slice(2).toLowerCase().padStart(64, '0'); };
export const dataWords = hex => { if (typeof hex !== 'string' || !/^0x([\da-f]{64})*$/i.test(hex)) throw Error('Ugyldig ABI-svar'); return hex.slice(2).match(/.{64}/g)?.map(x => BigInt(`0x${x}`)) ?? []; };
export function getRPCURL(env = process.env) {
  let url = env.ETH_RPC_URL?.trim();
  if (!url) {
    const key = env.ALCHEMY_API_KEY?.trim();
    if (!key || key.includes('REPLACE')) throw Error('Legg inn ETH_RPC_URL eller ALCHEMY_API_KEY i Netlify sine miljøvariabler.');
    const template = env.ALCHEMY_ENDPOINT || 'https://eth-mainnet.g.alchemy.com/v2/{API_KEY}';
    if (template.split('{API_KEY}').length !== 2) throw Error('Endpoint-malen må inneholde {API_KEY} én gang.');
    if (new URL(template).hostname !== 'eth-mainnet.g.alchemy.com') throw Error('Alchemy-malen må bruke Ethereum mainnet.');
    url = template.replace('{API_KEY}', encodeURIComponent(key));
  }
  let u; try { u = new URL(url); } catch { throw Error('RPC-endpoint er ugyldig.'); }
  if (u.protocol !== 'https:' || u.username || u.password || u.hash || /\s/.test(url)) throw Error('Bruk et HTTPS-RPC-endpoint uten brukernavn eller fragment.');
  return url;
}
export class RPC {
  constructor(url, fetcher = fetch) { this.url = url; this.fetcher = fetcher; this.count = 0; }
  async request(method, params = []) {
    if (!['eth_chainId', 'eth_getBlockByNumber', 'eth_call', 'eth_feeHistory', 'eth_maxPriorityFeePerGas', 'eth_getLogs'].includes(method)) throw Error('Kun lesing er tillatt.');
    let response;
    try { response = await this.fetcher(this.url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ jsonrpc: '2.0', id: ++this.count, method, params }), signal: AbortSignal.timeout(7000) }); }
    catch { throw Error('RPC-forbindelsen svarte ikke innen fristen.'); }
    if (!response.ok) throw Error(`RPC HTTP ${response.status}. Kontroller tilgang eller kvote i Alchemy.`);
    let data; try { data = await response.json(); } catch { throw Error('RPC ga et ugyldig svar.'); }
    if (data.error) throw Error(`RPC-feil ${Number(data.error.code) || 'ukjent'} (detaljer skjult).`);
    if (data.result === undefined || data.result === null) throw Error('RPC mangler data.');
    return data.result;
  }
  async call(to, data, block) { return dataWords(await this.request('eth_call', [{ to, data }, `0x${block.toString(16)}`])); }
}
export function quoteData(venue, input, output, amount) {
  if (venue.kind === 'v2') return '0xd06ca61f' + word(amount) + word(64) + word(2) + addressWord(input) + addressWord(output);
  return '0xc6a5026a' + addressWord(input) + addressWord(output) + word(amount) + word(venue.fee) + word(0);
}
export { word };
