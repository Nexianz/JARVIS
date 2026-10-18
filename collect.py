"""Historical collector: durable estimated-CU guard, sampling and prior-Swap filter.
No real transactions or contract deployments. EVM replay uses only a disposable local state override.
"""
import argparse,pathlib,os,json,hashlib,sys,shutil,contextlib
from chain import *
from market import *
from fork import Fork
from quota import QuotaClient,QuotaGateway,QuotaStop,DEFAULT_MAX_CU
from selection import SwapFilter,Checkpoints,sampled
from hardforks import hardfork_for_range

def fee_tip(rpc,b):return priority_fee(rpc,b)
def parser():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--start',required=True);ap.add_argument('--end',required=True)
    ap.add_argument('--output',default='results/run');ap.add_argument('--rpc-budget',type=int,default=100000)
    ap.add_argument('--max-cu',type=int,default=DEFAULT_MAX_CU,help='Cumulative ESTIMATED CU cap, including resume; default 5%% of 30 million')
    ap.add_argument('--quota-dir',default='.cache/alchemy',help='Shared durable ledger and immutable archive cache; reuse on resume')
    ap.add_argument('--every-n-blocks',type=int,default=1,help='Evaluate b only when (b-first) %% N == 0')
    ap.add_argument('--log-chunk-blocks',type=int,default=10,help='Swap log ranges, max 10 blocks')
    ap.add_argument('--retry-uncertain',action='store_true',help='Explicitly permit retry after unknown transport delivery; may duplicate upstream work and is charged again')
    ap.add_argument('--smoke-blocks',type=int,default=0,help='Diagnostic ONLY; cannot produce a valid study')
    ap.add_argument('--fx-csv');ap.add_argument('--capital-nok',type=float,default=5000)
    return ap

def evaluate_block(rpc,market,fork,meter,b,ref_cap):
    p=b-1;prev=rpc.block(p);block=rpc.block(b)
    if block['parentHash']!=prev['hash']:raise RuntimeError('Reorg/inconsistent archive data')
    if next_base(prev)!=int(block['baseFeePerGas'],16):raise RuntimeError('Unsupported base-fee rules/header inconsistency')
    snap=market.snapshot(p);pred_tip=fee_tip(rpc,p);actual_tip=fee_tip(rpc,b)
    simblock=dict(block,timestamp=hex(int(prev['timestamp'],16)+12),miner=prev['miner'],priorityFeeWei=pred_tip)
    row=dict(block=b,selection='evaluated',hash=block['hash'],parent=prev['hash'],timestamp=int(block['timestamp'],16),day=day(int(block['timestamp'],16)),state_block=p,base_wei=int(block['baseFeePerGas'],16),tip_prior_wei=pred_tip,tip_current_measured_wei=actual_tip,tip_prior_source=rpc.priority_fee_sources[p],tip_current_source=rpc.priority_fee_sources[b],snapshot=snap,candidates=[],screen_positive=0,evm_rejected=0)
    def execute(c,flash,**kwargs):
        try:return fork.execute(p,simblock,c,flash,**kwargs)
        finally:meter.raise_if_stopped()
    for flash in [True,False]:
        for a in range(4):
            for z in range(4):
                if a==z:continue
                caps=[10_000_000*10**6] if flash else [int(ref_cap*f) for f in [.25,.5,.75,1]];seen=set()
                for cap in caps:
                    frontier=market.optimize(a,z,p,snap,flash,cap)
                    for c in frontier or []:
                        if c['amount'] in seen:continue
                        seen.add(c['amount']);row['screen_positive']+=1
                        sim=execute(c,flash)
                        if not sim['ok']:
                            if sim['revert_reason']!='minProfit':raise RuntimeError('Unexpected local replay failure: '+str(sim['revert_reason']))
                            row['evm_rejected']+=1;continue
                        failed=execute(c,flash,force_revert=True)
                        if failed['ok'] or failed['revert_reason']!='minProfit' or failed['gas']>=1800000:raise RuntimeError('Invalid late-revert gas measurement')
                        guarded=execute(c,flash,min_profit=sim['profit'])
                        if not guarded['ok'] or guarded['profit']!=sim['profit']:raise RuntimeError('minProfit replay inconsistent')
                        # Future-block competition is consulted after finding/simulating the candidate.
                        comp=market.competition(b,a,z)
                        c.update(mode='A' if flash else 'B',profit_usdc=sim['profit']/1e6,gas=guarded['gas'],revert_gas=failed['gas'],competition=comp)
                        row['candidates'].append(c)
    return row

def run(args,meter):
    rpc=meter.rpc;start,end=timestamp(args.start),timestamp(args.end)
    out=pathlib.Path(args.output);out.mkdir(parents=True,exist_ok=True);mp=out/'manifest.json'
    if int(rpc.call('eth_chainId',[]),16)!=1:raise RuntimeError('Ethereum mainnet only')
    # Freeze block bounds on first run. Resume never redoes time-to-block discovery.
    old=json.loads(mp.read_text()) if mp.exists() else None
    hardfork=hardfork_for_range(start,end)
    settings=dict(start=args.start,end_exclusive=args.end,capital_nok=args.capital_nok,every_n_blocks=args.every_n_blocks,swap_filter='prior_block_only',log_chunk_blocks=args.log_chunk_blocks,smoke_only=bool(args.smoke_blocks),smoke_blocks=args.smoke_blocks,hardfork=hardfork,verify_replay=bool(getattr(args,'verify_replay',False)))
    if old:
        for k,v in settings.items():
            if old.get(k)!=v:raise RuntimeError('Resume settings differ. Use a new output folder; quota/cache stay shared.')
        first,last=old['first'],old['last']
    else:
        latest=rpc.block(int(rpc.call('eth_blockNumber',[]),16))
        if end>int(latest['timestamp'],16)-86400:raise RuntimeError('Use a fully historical range ending >=24h before head')
        first=rpc.at_time(start);last=rpc.at_time(end)-1
        if args.smoke_blocks:last=min(last,first+args.smoke_blocks-1)
    source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in list(pathlib.Path('.').glob('*.py'))+list(pathlib.Path('contracts').glob('*.sol'))+[pathlib.Path('cu_costs.json')]}
    artifact=hashlib.sha256(pathlib.Path('out/Replay.sol/Replay.json').read_bytes()).hexdigest()
    if old and (old.get('source_sha256')!=source_hashes or old.get('artifact_sha256')!=artifact):raise RuntimeError('Source/artifact differs from checkpoint. Choose a new output folder; cache is reusable.')
    checkpoints=Checkpoints(out/'blocks.jsonl')
    if any(b<first or b>last for b in checkpoints.completed):raise RuntimeError('Checkpoint contains blocks outside the selected period')
    manifest=dict(schema=2,**settings,first=first,last=last,blocks=last-first+1,source_sha256=source_hashes,artifact_sha256=artifact,status='INCOMPLETE',complete=False,scope='USDC/WETH; same four canonical pools',quota_label='BEREGNET fra ANTATTE CU-satser',sampling_warning='Sampling/Swap filter omits opportunities. No unbiased full-period PnL inference.',quota_dir=str(pathlib.Path(args.quota_dir).resolve()))
    # Save bounds before initialization so interrupted setup also resumes deterministically.
    mp.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    try:
        fx=old.get('fx') if old else None
        if fx is None:fx=parse_fx(pathlib.Path(args.fx_csv).read_text(encoding='utf-8-sig')) if args.fx_csv else fx_download(args.start,args.end,out)
        fx_at(fx,args.start);fx_at(fx,day(int(rpc.block(last)['timestamp'],16)));manifest['fx']=fx
        market=Market(rpc,first-1);initial=market.snapshot(first-1)
        ref_cap=old.get('reference_own_usdc') if old else None
        if ref_cap is None:ref_cap=int(args.capital_nok*.8*.997/fx_at(fx,args.start)/initial['usdc_usd']*1e6)
        manifest.update(pools=market.pools,reference_own_usdc=ref_cap)
        swap_filter=SwapFilter(rpc,market.pools,first-1,last-1,args.log_chunk_blocks)
        # Every Anvil-origin archive request must pass through the same guard/cache.
        with QuotaGateway(meter) as gateway:
            fork=None
            try:
                if settings['verify_replay'] and not (old or {}).get('replay_verified'):
                    print('Checking local minProfit replay for '+args.start+' ('+hardfork+'); all archive reads metered.',flush=True)
                    fork=Fork(gateway.url,hardfork=hardfork)
                    verify_replay(rpc,market,fork,meter,first)
                    manifest['replay_verified']=True
                    mp.write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
                elif (old or {}).get('replay_verified'):manifest['replay_verified']=True
                for b in range(first,last+1):
                    if b in checkpoints.completed:continue
                    row=dict(block=b,state_block=b-1)
                    if not sampled(b,first,args.every_n_blocks):row['selection']='sampling_skipped'
                    elif not swap_filter.active(b-1):row['selection']='no_prior_swap'
                    else:
                        if fork is None:fork=Fork(gateway.url,hardfork=hardfork)
                        row=evaluate_block(rpc,market,fork,meter,b,ref_cap)
                    checkpoints.add(row)
                    if (b-first)%100==0:
                        report=meter.summary();print(f'{b-first+1}/{last-first+1} blokker sjekket; BEREGNET CU reservert {report["estimated_cu_reserved"]}/{args.max_cu}; utvalg {checkpoints.counts}',flush=True)
            finally:
                if fork:fork.close()
        manifest['complete']=len(checkpoints.completed)==last-first+1
        manifest['status']='SMOKE_ONLY' if args.smoke_blocks else 'FILTERED_COLLECTION'
        print('Utvalgsinnsamling fullført. Dette er ikke en ferdig resultatrapport.')
    except BaseException:
        meter.raise_if_stopped();raise
    finally:
        manifest['completed_blocks']=len(checkpoints.completed);manifest['selection_counts']=checkpoints.counts
        manifest['cu_summary']=meter.summary();mp.write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')

def verify_replay(rpc,market,fork,meter,b):
    prev=rpc.block(b-1);block=dict(rpc.block(b),timestamp=hex(int(prev['timestamp'],16)+12),miner=prev['miner'],priorityFeeWei=fee_tip(rpc,b-1))
    for flash in (True,False):
        try:result=fork.execute(b-1,block,dict(first=0,second=1,amount=100*10**6),flash,force_revert=True,prefund=10*10**6 if flash else 0)
        finally:meter.raise_if_stopped()
        if result['ok'] or result['revert_reason']!='minProfit':raise RuntimeError('Date-specific local replay did not reach minProfit: '+str(result['revert_reason']))
    print('PASS: date-specific local replay reaches minProfit in both modes. No real transaction/deployment.',flush=True)

def validate_args(args,pilot=False):
    if args.every_n_blocks<1 or not 1<=args.log_chunk_blocks<=10 or args.smoke_blocks<0:raise ValueError('Invalid sampling/log chunk/smoke-block count')
    start,end=timestamp(args.start),timestamp(args.end)
    hardfork_for_range(start,end)
    if pilot:
        if end-start!=86400 or args.smoke_blocks:raise ValueError('Pilot must cover exactly one UTC day without smoke truncation')
    elif end-start<30*86400 and not args.smoke_blocks:raise ValueError('Use pilot.py for the one-day pilot')
    # No dependency installation, node connection or deployment is done by this step.
    if not shutil.which('anvil') or not pathlib.Path('out/Replay.sol/Replay.json').exists():raise RuntimeError('Local replay prerequisites are not verified. Step 1 is quota infrastructure only; do not start collection yet.')

def main():
    args=parser().parse_args();validate_args(args)
    load_env()
    with QuotaClient(rpc_url(),args.quota_dir,args.max_cu,max_requests=args.rpc_budget,retry_uncertain=args.retry_uncertain) as meter:
        try:run(args,meter)
        finally:
            meter.write_summary();s=meter.summary()
            print(f'BEREGNET CU-estimat: {s["estimated_cu_reserved"]}; denne prosessen {s["estimated_cu_this_invocation"]}; grense {args.max_cu}. ANTATTE satser, ikke fakturert CU.')
            for method,r in s['by_method'].items():print(f'  {method}: {r["attempts"]} lokalt registrerte forsøk × {r["estimated_cu_per_attempt"]} ANTATT CU = {r["estimated_cu"]} BEREGNET CU')
if __name__=='__main__':
    try:main()
    except (RPCError,BudgetStop,RuntimeError,ValueError,FileNotFoundError) as e:print(type(e).__name__+': '+str(e),file=sys.stderr);sys.exit(2)
