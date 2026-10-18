"""Counterfactual assumptions and hard portfolio risk controls. No network access."""
from dataclasses import dataclass,asdict
import random,datetime,collections,math
from market import fx_at
@dataclass(frozen=True)
class Assumptions:
    name:str='realistisk'
    private_inclusion:float=.10
    public_inclusion:float=.95
    failure:float=.10
    adverse_profit_haircut:float=.10
    bid:float=.95
    initial_conversion_fee:float=.003
    minimum_net_nok:float=1.0
    margin_fraction:float=.25
    maximum_daily_loss_nok:float=50.0
    maximum_weekly_loss_nok:float=150.0
    maximum_gas_nok:float=30.0
    maximum_gas_price_gwei:float=100.0
    maximum_failures_hour:int=3
    gas_safety_units:int=512
SCENARIOS={
 'pessimistisk':Assumptions(name='pessimistisk',private_inclusion=.01,failure=.25,adverse_profit_haircut=.25,bid=.99),
 'realistisk':Assumptions(),
 'optimistisk':Assumptions(name='optimistisk',private_inclusion=.50,failure=.02,adverse_profit_haircut=.02,bid=.80),
}
def quantile(xs,q):
    xs=sorted(xs)
    if not xs:raise ValueError('Empty distribution')
    pos=(len(xs)-1)*q;i=int(pos);j=min(i+1,len(xs)-1)
    return xs[i]+(xs[j]-xs[i])*(pos-i)
@dataclass
class Risk:
    settings:Assumptions
    day:str=''
    week:str=''
    dayloss:float=0.
    weekloss:float=0.
    failures:object=None
    def __post_init__(self):self.failures=collections.deque()
    def reset(self,t):
        dt=datetime.datetime.fromtimestamp(t,datetime.timezone.utc);d=dt.date().isoformat();w=str(dt.date().isocalendar()[:2])
        if d!=self.day:self.day=d;self.dayloss=0.
        if w!=self.week:self.week=w;self.weekloss=0.
        while self.failures and self.failures[0]<=t-3600:self.failures.popleft()
    def allow(self,t,worst_loss,gas_nok,price_gwei):
        self.reset(t);s=self.settings
        return (self.dayloss+worst_loss<=s.maximum_daily_loss_nok and self.weekloss+worst_loss<=s.maximum_weekly_loss_nok and len(self.failures)<s.maximum_failures_hour and gas_nok<=s.maximum_gas_nok and price_gwei<=s.maximum_gas_price_gwei)
    def record(self,t,pnl,failed):
        self.reset(t)
        if pnl<0:self.dayloss-=pnl;self.weekloss-=pnl
        if failed:self.failures.append(t)

def economics(c,row,fx,s):
    usd_nok=fx_at(fx,row['day']);snap=row['snapshot'];ethnok=snap['eth_usd']*usd_nok;usdcnok=snap['usdc_usd']*usd_nok
    # Tip submitted using previous-block measured median only. Current block median never enters the decision.
    price=row['base_wei']+row['tip_prior_wei']
    gas_eth=(c['gas']+s.gas_safety_units)*price/1e18;fail_eth=(c['revert_gas']+s.gas_safety_units)*price/1e18
    gross=c['profit_usdc']*usdcnok
    aftergas=gross-gas_eth*ethnok
    bid_nok=max(0,aftergas)*s.bid
    net=aftergas-bid_nok
    # Margin is a required retained buffer, not a fictional expenditure.
    minimum=s.minimum_net_nok+s.margin_fraction*gas_eth*ethnok
    contract_min_usdc=(gas_eth*ethnok+bid_nok+minimum)/usdcnok
    return dict(ethnok=ethnok,usdcnok=usdcnok,price=price,gas_eth=gas_eth,fail_eth=fail_eth,bid_eth=bid_nok/ethnok,net=net,minimum=minimum,contract_min_usdc=contract_min_usdc)

def simulate(rows,manifest,settings,mode='A',channel='private',seed=1,record_curve=True):
    if not rows:raise ValueError('No blocks')
    rng=random.Random(seed);fx=manifest['fx'];initial=manifest['capital_nok'];first=rows[0]
    usd_nok=fx_at(fx,first['day']);snap=first['snapshot'];fee=settings.initial_conversion_fee
    eth=initial*(1 if mode=='A' else .2)*(1-fee)/(snap['eth_usd']*usd_nok)
    cash=0. if mode=='A' else initial*.8*(1-fee)/(snap['usdc_usd']*usd_nok)
    eth0,cash0=eth,cash;risk=Risk(settings);peak=initial;draw=0;curve=[];events=[]
    stats=collections.Counter();gas_eth_total=0.;gas_nok_total=0.;bid_eth_total=0.;bid_nok_total=0.;strategy_pnl=-initial*fee;last_date=None;consumed_pool_state={}
    def value(row):
        f=fx_at(fx,row['day']);s=row['snapshot'];return (eth*s['eth_usd']+cash*s['usdc_usd'])*f
    def benchmark(row):
        f=fx_at(fx,row['day']);s=row['snapshot'];return (eth0*s['eth_usd']+cash0*s['usdc_usd'])*f
    def finish_day(row):
        if record_curve:curve.append(dict(day=row['day'],equity_nok=value(row),hold_benchmark_nok=benchmark(row),strategy_pnl_at_trade_fx_nok=strategy_pnl,eth_balance=eth,usdc_balance=cash))
    previous=None
    for row in rows:
        if previous and previous['day']!=row['day']:finish_day(previous)
        choices=[];by_route={}
        for c in row['candidates']:
            if c['mode']!=mode:continue
            if any(consumed_pool_state.get(i)==row['snapshot']['state'][i] for i in [c['first'],c['second']]):continue
            if mode=='B' and c['amount']/1e6>cash:continue
            # We may inspect hypothetical feasibility for each route; submit at most one per block.
            e=economics(c,row,fx,settings)
            if e['net']<e['minimum']:continue
            key=(c['first'],c['second'])
            if key not in by_route or e['net']>by_route[key][0]:by_route[key]=(e['net'],c,e)
        stats['profitable_route_block_opportunities']+=len(by_route)
        choices=list(by_route.values())
        if choices:
            _,c,e=max(choices,key=lambda x:x[0]);stats['opportunity_blocks']+=1
            # Competition is looked up ONLY AFTER route selection. Never cherry-pick the route not taken by rivals.
            contested=bool(c['competition']['same_route_cycle_txs'])
            if contested:stats['taken_by_other_proxy']+=1
            cost_success=e['gas_eth']+e['bid_eth'];worst_fail=e['fail_eth']*e['ethnok']
            gas_nok=e['gas_eth']*e['ethnok']
            if not risk.allow(row['timestamp'],worst_fail,gas_nok,e['price']/1e9):stats['risk_blocked']+=1
            elif eth<max(cost_success,e['fail_eth']):stats['gas_wallet_blocked']+=1
            else:
                stats['attempts']+=1
                # Private losing bundles pay zero. Public colliding transactions are assumed included/reverted.
                inclusion=settings.private_inclusion if channel=='private' else settings.public_inclusion
                if contested and channel=='private':stats['not_included']+=1
                elif rng.random()>inclusion:stats['not_included']+=1
                else:
                    haircut=rng.uniform(0,settings.adverse_profit_haircut)
                    paid_profit=c['profit_usdc']*(1-haircut)
                    failed=contested or rng.random()<settings.failure or paid_profit<e['contract_min_usdc']
                    if failed:
                        cost=e['fail_eth'];eth-=cost;loss=cost*e['ethnok'];strategy_pnl-=loss;risk.record(row['timestamp'],-loss,True)
                        stats['failed']+=1;stats['gas_units']+=c['revert_gas']+settings.gas_safety_units
                        gas_eth_total+=cost;gas_nok_total+=loss
                        if record_curve:events.append(dict(block=row['block'],outcome='revert',pnl_nok=-loss,minProfit_usdc=e['contract_min_usdc']))
                    else:
                        eth-=cost_success;cash+=paid_profit
                        pnl=paid_profit*e['usdcnok']-cost_success*e['ethnok'];strategy_pnl+=pnl;risk.record(row['timestamp'],pnl,False)
                        for pool_i in [c['first'],c['second']]:consumed_pool_state[pool_i]=row['snapshot']['state'][pool_i]
                        stats['wins']+=1;stats['gas_units']+=c['gas']+settings.gas_safety_units
                        gas_eth_total+=e['gas_eth'];gas_nok_total+=gas_nok;bid_eth_total+=e['bid_eth'];bid_nok_total+=e['bid_eth']*e['ethnok']
                        if record_curve:events.append(dict(block=row['block'],outcome='win_counterfactual',pnl_nok=pnl,minProfit_usdc=e['contract_min_usdc']))
        v=value(row);peak=max(peak,v);draw=max(draw,(peak-v)/peak);previous=row
    finish_day(rows[-1]);final=value(rows[-1]);hold=benchmark(rows[-1])
    return dict(mode=mode,channel=channel,assumptions=asdict(settings),initial_nok=initial,final_nok=final,total_return_nok=final-initial,hold_benchmark_nok=hold,incremental_vs_hold_nok=final-hold,strategy_pnl_trade_fx_nok=strategy_pnl,max_drawdown_fraction=draw,gas_eth=gas_eth_total,gas_nok_at_trade_fx=gas_nok_total,builder_bid_eth=bid_eth_total,builder_bid_nok_at_trade_fx=bid_nok_total,counts=dict(stats),curve=curve,events=events,**{'verdi_status':'BEREGNET: kjededata + ANTATTE utfall; ingen faktisk realisert handel'})
