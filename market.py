from fractions import Fraction
import math,datetime,json,csv,io,pathlib,urllib.request,hashlib
from chain import *
USDC='0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48'
WETH='0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
PROVIDER='0x2f39d218133afab8f2b819b1066c7e434ad94e9e'
QUOTER='0x61ffe014ba17989e743c5f6cb21bf9697530b21e'
ETHUSD='0x5f4ec3df9cbd43714fe2740f5e3616155c5b8419'
USDCUSD='0x8fffffd4afb6115b954bd326cbe7b4ba576818f6'
FACTORIES=['0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f','0xc0aee478e3658e2610c5f7a4a2e1777ce9e4f2ac','0x1f98431c8ad98523631ae4a59f267346ea31f984','0x1f98431c8ad98523631ae4a59f267346ea31f984']
ROUTERS=['0x7a250d5630b4cf539739df2c5dacb4c659f2488d','0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f']
NAMES=['UniswapV2-30bp','SushiV2-30bp','UniswapV3-5bp','UniswapV3-30bp']
SWAP2=topic('Swap(address,uint256,uint256,uint256,uint256,address)')
SWAP3=topic('Swap(address,address,int256,int256,uint160,uint128,int24)')
def day(t):return datetime.datetime.fromtimestamp(t,datetime.timezone.utc).date().isoformat()
def timestamp(s):return int(datetime.datetime.fromisoformat(s).replace(tzinfo=datetime.timezone.utc).timestamp())
def next_base(b):
    base=int(b['baseFeePerGas'],16);used=int(b['gasUsed'],16);target=int(b['gasLimit'],16)//2
    if used==target:return base
    if used>target:return base+max(1,base*(used-target)//target//8)
    return base-base*(target-used)//target//8

def fx_download(start,end,folder):
    """Measured daily USD/NOK. Weekends use latest available prior business day."""
    folder=pathlib.Path(folder);folder.mkdir(exist_ok=True,parents=True)
    p=folder/f'fx-{start}-{end}.csv'
    if not p.exists():
        earlier=(datetime.date.fromisoformat(start)-datetime.timedelta(days=10)).isoformat()
        url=f'https://data.norges-bank.no/api/data/EXR/B.USD.NOK.SP?startPeriod={earlier}&endPeriod={end}&format=csv-:-comma'
        try:
            with urllib.request.urlopen(url,timeout=60) as r:text=r.read().decode('utf-8-sig')
        except Exception as e:raise RuntimeError('Norges Bank download failed; provide CSV as documented. '+type(e).__name__) from None
        # Validate before saving, to avoid caching HTML error pages.
        parse_fx(text);p.write_text(text,encoding='utf-8')
    return parse_fx(p.read_text(encoding='utf-8-sig'))
def parse_fx(text):
    dialect=csv.Sniffer().sniff(text[:8192],delimiters=',;\t')
    rows=list(csv.DictReader(io.StringIO(text),dialect=dialect));out={}
    for r in rows:
        if r.get('BASE_CUR','USD')!='USD' or r.get('QUOTE_CUR','NOK')!='NOK':continue
        if r.get('UNIT_MULT','0') not in ('','0'):raise ValueError('Unexpected FX unit multiplier')
        if r.get('OBS_VALUE') and r.get('TIME_PERIOD'):out[r['TIME_PERIOD']]=float(r['OBS_VALUE'].replace(',','.'))
    if not out or any(v<=0 for v in out.values()):raise ValueError('CSV must contain daily TIME_PERIOD and OBS_VALUE for USD/NOK')
    return out
def fx_at(fx,date):
    choices=[d for d in fx if d<=date]
    if not choices:raise ValueError('No historical FX on/before '+date)
    d=max(choices)
    if (datetime.date.fromisoformat(date)-datetime.date.fromisoformat(d)).days>5:raise ValueError('Stale/missing FX')
    return fx[d]
class Market:
    def __init__(self,rpc,block,min_age_days=30,min_depth_usd=1000000):
        self.rpc=rpc;self.pools=[];self.min_depth=min_depth_usd
        t=int(rpc.block(block)['timestamp'],16);old=rpc.at_time(t-min_age_days*86400)
        for i in range(4):
            if i<2:p=addr(rpc.ethcall(FACTORIES[i],'getPair(address,address)',USDC,WETH,block=block)[0])
            else:p=addr(rpc.ethcall(FACTORIES[i],'getPool(address,address,uint24)',USDC,WETH,500 if i==2 else 3000,block=block)[0])
            if int(p,16)==0:raise RuntimeError('Pool missing at historical start')
            if rpc.call('eth_getCode',[p,hex(old)])=='0x':raise RuntimeError('Pool fails minimum historical age')
            token0=addr(rpc.ethcall(p,'token0()',block=block)[0]);token1=addr(rpc.ethcall(p,'token1()',block=block)[0])
            if {token0,token1}!={USDC,WETH}:raise RuntimeError('Token allowlist violation')
            if i>=2 and rpc.ethcall(p,'fee()',block=block)[0]!=(500 if i==2 else 3000):raise RuntimeError('Fee tier mismatch')
            self.pools.append({'address':p,'usdc0':token0==USDC,'name':NAMES[i]})
    def oracle(self,address,b,t):
        decimals=self.rpc.ethcall(address,'decimals()',block=b)[0]
        r=self.rpc.ethcall(address,'latestRoundData()',block=b)
        if r[1]>=1<<255 or r[1]<=0 or r[3]>t or t-r[3]>86400 or r[4]<r[0]:raise RuntimeError('Invalid/stale Chainlink observation')
        return r[1]/10**decimals
    def snapshot(self,b):
        t=int(self.rpc.block(b)['timestamp'],16)
        eth=self.oracle(ETHUSD,b,t);usdc=self.oracle(USDCUSD,b,t)
        pool=addr(self.rpc.ethcall(PROVIDER,'getPool()',block=b)[0])
        premium=self.rpc.ethcall(pool,'FLASHLOAN_PREMIUM_TOTAL()',block=b)[0]
        # Aave V3 USDC aToken liquidity; reserve data layout is stable in supported 2024+ V3 releases.
        reserve=self.rpc.ethcall(pool,'getReserveData(address)',USDC,block=b)
        if len(reserve)<9:raise RuntimeError('Unsupported Aave reserve ABI')
        atoken=addr(reserve[8]);liquidity=self.rpc.ethcall(USDC,'balanceOf(address)',atoken,block=b)[0]
        depths=[];state=[]
        for i,p in enumerate(self.pools):
            depth=self.rpc.ethcall(USDC,'balanceOf(address)',p['address'],block=b)[0]/1e6
            depths.append(depth)
            if i<2:state.append(self.rpc.ethcall(p['address'],'getReserves()',block=b)[:2])
            else:
                state.append([self.rpc.ethcall(p['address'],'slot0()',block=b),self.rpc.ethcall(p['address'],'liquidity()',block=b)[0]])
        return dict(eth_usd=eth,usdc_usd=usdc,premium_bps=premium,aave_pool=pool,flash_liquidity=liquidity,depths=depths,state=state)
    def quote(self,i,amount,usdc_in,b):
        if amount<=0:return 0
        a,z=(USDC,WETH) if usdc_in else (WETH,USDC)
        if i<2:
            # Pure exact constant-product integer formula; reserves from pinned historical eth_call.
            p=self.pools[i];r=self.rpc.ethcall(p['address'],'getReserves()',block=b)
            reserve_in,reserve_out=(r[0],r[1]) if (p['usdc0']==usdc_in) else (r[1],r[0])
            return amount*997*reserve_out//(reserve_in*1000+amount*997)
        # QuoterV2 exactInputSingle is deliberately non-view, safe under eth_call.
        return self.rpc.ethcall(QUOTER,'quoteExactInputSingle((address,address,uint256,uint24,uint160))',a,z,amount,500 if i==2 else 3000,0,block=b)[0]
    def optimize(self,a,z,b,snap,flash,cap):
        if min(snap['depths'][a],snap['depths'][z])*snap['usdc_usd']<self.min_depth:return None
        def marginal(i,usdc_in):
            p=self.pools[i];s=snap['state'][i]
            if i<2:
                ratio=Fraction(s[1],s[0]);fee=Fraction(997,1000)
            else:
                ratio=Fraction(s[0][0]**2,2**192);fee=Fraction(1000000-(500 if i==2 else 3000),1000000)
            return (ratio if p['usdc0']==usdc_in else 1/ratio)*fee
        repayment=Fraction(10000+(snap['premium_bps'] if flash else 0),10000)
        if marginal(a,True)*marginal(z,False)<repayment-Fraction(1,1000000):return None
        # Cap at 10% of real pool token balances and 90% of Aave available liquidity.
        high=int(min(cap,0.10*snap['depths'][a]*1e6,0.10*snap['depths'][z]*1e6,0.90*snap['flash_liquidity'] if flash else cap))
        if min(snap['depths'][a],snap['depths'][z])*snap['usdc_usd']<self.min_depth or high<1000000:return None
        memo={}
        def f(x):
            x=max(1,min(high,int(x)))
            if x not in memo:
                out=self.quote(z,self.quote(a,x,True,b),False,b)
                premium=(x*snap['premium_bps']+5000)//10000 if flash else 0
                memo[x]=out-x-premium
            return memo[x]
        # Search logarithmic grid then refine locally. Numerical optimum, not a proof of global optimum.
        grid=sorted(set([int(10**(6+(math.log10(high)-6)*k/12)) for k in range(13)]+[high]))
        k=max(range(len(grid)),key=lambda j:f(grid[j]));lo=grid[max(0,k-1)];hi=grid[min(len(grid)-1,k+1)]
        for _ in range(22):
            m1=lo+(hi-lo)//3;m2=hi-(hi-lo)//3
            if f(m1)<f(m2):lo=m1
            else:hi=m2
        for x in [lo,hi,(lo+hi)//2]:f(x)
        x=max(memo,key=memo.get)
        return [dict(first=a,second=z,amount=k,quoted_profit=memo[k],search_cap=high,at_search_cap=k>=high*0.995) for k in sorted(set(grid+[x])) if memo[k]>0]
    def competition(self,b,a,z):
        logs=self.rpc.call('eth_getLogs',[{'fromBlock':hex(b),'toBlock':hex(b),'address':[self.pools[a]['address'],self.pools[z]['address']],'topics':[[SWAP2,SWAP3]]}])
        buy=set();sell=set();all_txs=set()
        for l in logs:
            all_txs.add(l['transactionHash']);i=a if l['address'].lower()==self.pools[a]['address'] else z
            w=words(l['data']);usdc0=self.pools[i]['usdc0']
            if l['topics'][0].lower()==SWAP2:
                uin,uout=(w[0],w[2]) if usdc0 else (w[1],w[3]);direction=uin>0 and uout==0
            else:
                v=w[0 if usdc0 else 1];direction=v>0 and v<1<<255
            if i==a and direction:buy.add(l['transactionHash'])
            if i==z and not direction:sell.add(l['transactionHash'])
        return {'same_route_cycle_txs':sorted(buy&sell),'any_pool_swap_txs':len(all_txs)}
