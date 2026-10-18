"""Standard-library Ethereum ABI, Keccak and read-only archived RPC with SQLite cache."""
import functools
import json, hashlib, sqlite3, time, urllib.request, urllib.error, urllib.parse, os
MASK=(1<<64)-1
RC=[0x1,0x8082,0x800000000000808a,0x8000000080008000,0x808b,0x80000001,0x8000000080008081,0x8000000000008009,0x8a,0x88,0x80008009,0x8000000a,0x8000808b,0x800000000000008b,0x8000000000008089,0x8000000000008003,0x8000000000008002,0x8000000000000080,0x800a,0x800000008000000a,0x8000000080008081,0x8000000000008080,0x80000001,0x8000000080008008]
ROT=[[0,36,3,41,18],[1,44,10,45,2],[62,6,43,15,61],[28,55,25,21,56],[27,20,39,8,14]]
def keccak(data):
    a=[0]*25; d=bytearray(data)
    padding=136-len(d)%136
    d.extend(bytes([129]) if padding==1 else bytes([1])+bytes(padding-2)+bytes([128]))
    for off in range(0,len(d),136):
        for i in range(17):a[i]^=int.from_bytes(d[off+8*i:off+8*i+8],'little')
        for rc in RC:
            c=[a[x]^a[x+5]^a[x+10]^a[x+15]^a[x+20] for x in range(5)]
            dd=[c[(x-1)%5]^((c[(x+1)%5]<<1 | c[(x+1)%5]>>63)&MASK) for x in range(5)]
            for x in range(5):
                for y in range(5):a[x+5*y]^=dd[x]
            b=[0]*25
            for x in range(5):
                for y in range(5):
                    v=a[x+5*y];r=ROT[x][y];b[y+5*((2*x+3*y)%5)]=((v<<r)|(v>>(64-r if r else 64)))&MASK
            for x in range(5):
                for y in range(5):a[x+5*y]=b[x+5*y]^((~b[(x+1)%5+5*y])&b[(x+2)%5+5*y])
            a[0]^=rc
    return b''.join(v.to_bytes(8,'little') for v in a)[:32]
def word(x):
    if isinstance(x,str):x=int(x,16)
    return int(x).to_bytes(32,'big').hex()
@functools.lru_cache(maxsize=256)
def selector(sig):return keccak(sig.encode()).hex()[:8]
def encode(sig,*args):return '0x'+selector(sig)+''.join(word(x) for x in args)
def words(raw):
    s=raw.removeprefix('0x')
    if len(s)%64:raise ValueError('Invalid ABI result')
    return [int(s[i:i+64],16) for i in range(0,len(s),64)]
def addr(n):return '0x'+word(n)[24:]
def topic(sig):return '0x'+keccak(sig.encode()).hex()
class RPCError(RuntimeError):pass
class BudgetStop(RuntimeError):pass
class RPC:
    READ={'eth_chainId','eth_blockNumber','eth_getBlockByNumber','eth_getCode','eth_getStorageAt','eth_call','eth_getLogs','eth_feeHistory','eth_getTransactionReceipt'}
    def __init__(self,url,cache=None,budget=100000):
        self.url=url;self.calls=0;self.budget=budget
        self.db=sqlite3.connect(cache) if cache else None
        if self.db:self.db.execute('CREATE TABLE IF NOT EXISTS rpc (k TEXT PRIMARY KEY, v TEXT)')
    def call(self,method,params,cache=True):
        if method not in self.READ:raise RPCError('Upstream is READ ONLY')
        return self._request(method,params,cache)
    def _request(self,method,params,cache=False):
        key=json.dumps([method,params],sort_keys=True,separators=(',',':'))
        if cache and self.db:
            row=self.db.execute('SELECT v FROM rpc WHERE k=?',(key,)).fetchone()
            if row:return json.loads(row[0])
        if self.calls>=self.budget:raise BudgetStop('RPC budget reached; cache retained. Increase --rpc-budget to resume.')
        for attempt in range(5):
            self.calls+=1
            try:
                req=urllib.request.Request(self.url,data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode(),headers={'Content-Type':'application/json'})
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({})).open if urllib.parse.urlsplit(self.url).hostname=='127.0.0.1' else urllib.request.urlopen
                with opener(req,timeout=90) as r:d=json.load(r)
                if 'error' in d:
                    code=d['error'].get('code');msg=d['error'].get('message','')
                    # Do not include endpoint-bearing server messages in logs.
                    if code in (429,-32005) and attempt<4:time.sleep(2**attempt);continue
                    raise RPCError(f'{method} RPC error code {code}; execution reverted={"revert" in msg.lower()}')
                result=d['result']
                if cache and self.db:self.db.execute('INSERT OR REPLACE INTO rpc VALUES (?,?)',(key,json.dumps(result)));self.db.commit()
                return result
            except urllib.error.HTTPError as e:
                if e.code in (429,502,503,504) and attempt<4:time.sleep(2**attempt);continue
                raise RPCError(f'{method}: HTTP {e.code}; check key/access for 401/403 or quota for 429 (endpoint redacted)') from None
            except (urllib.error.URLError,TimeoutError) as e:
                if attempt==4:raise RPCError(f'{method}: transport failure ({type(e).__name__}); endpoint redacted') from None
                time.sleep(2**attempt)
        raise RPCError('Retries exhausted')
    def ethcall(self,to,sig,*args,block):return words(self.call('eth_call',[{'to':to,'data':encode(sig,*args)},hex(block)]))
    def block(self,n):
        b=self.call('eth_getBlockByNumber',[hex(n),False]);assert b,'Missing block';return b
    def at_time(self,t):
        lo=17000000;hi=int(self.call('eth_blockNumber',[],False),16)
        while lo<hi:
            m=(lo+hi)//2
            if int(self.block(m)['timestamp'],16)<t:lo=m+1
            else:hi=m
        return lo

def load_env(path='.env'):
    if not os.path.exists(path):return
    for line in open(path,encoding='utf-8-sig'):
        line=line.strip()
        if line and not line.startswith('#') and '=' in line:
            k,v=line.split('=',1);os.environ.setdefault(k.strip(),v.strip().strip('\"\''))

DEFAULT_ALCHEMY_ENDPOINT='https://eth-mainnet.g.alchemy.com/v2/{API_KEY}'
def rpc_url(environ=None):
    """Resolve a full URL or an endpoint template + separate secret, without logging either."""
    values=os.environ if environ is None else environ
    direct=values.get('ETH_RPC_URL','').strip()
    if direct and 'REPLACE' not in direct:
        url=direct
    else:
        endpoint=values.get('ALCHEMY_ENDPOINT',DEFAULT_ALCHEMY_ENDPOINT).strip()
        key=values.get('ALCHEMY_API_KEY','').strip()
        if not key or 'REPLACE' in key:raise RuntimeError('Missing API key. Run python3 rpc_setup.py or edit local .env; do not paste the key in chat.')
        if endpoint.count('{API_KEY}')!=1:raise RuntimeError('ALCHEMY_ENDPOINT must contain exactly one {API_KEY} placeholder; alternatively set full ETH_RPC_URL.')
        target=urllib.parse.urlsplit(endpoint)
        if target.hostname!='eth-mainnet.g.alchemy.com':raise RuntimeError('Separate Alchemy key requires Ethereum mainnet Alchemy endpoint; use ETH_RPC_URL for another provider.')
        url=endpoint.replace('{API_KEY}',urllib.parse.quote(key,safe=''))
    try:parsed=urllib.parse.urlsplit(url)
    except ValueError:raise RuntimeError('Invalid HTTPS RPC endpoint (redacted).') from None
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or '{' in url or any(c.isspace() for c in url):
        raise RuntimeError('RPC endpoint must be a complete HTTPS URL without userinfo or whitespace (redacted).')
    return url
