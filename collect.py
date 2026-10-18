"""Historical all-block collector. Never signs or broadcasts to mainnet."""
import argparse,pathlib,os,json,hashlib,sys,datetime,shutil
from chain import *
from market import *
from fork import Fork

def fee_tip(rpc,b):return priority_fee(rpc,b)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--start',required=True);ap.add_argument('--end',required=True)
    ap.add_argument('--output',default='results/run');ap.add_argument('--rpc-budget',type=int,default=100000)
    ap.add_argument('--smoke-blocks',type=int,default=0,help='Diagnostic ONLY; cannot produce a valid 30-day study')
    ap.add_argument('--fx-csv');ap.add_argument('--capital-nok',type=float,default=5000)
    args=ap.parse_args();load_env();url=rpc_url()
    start,end=timestamp(args.start),timestamp(args.end)
    if start<timestamp('2025-05-08') or end>timestamp('2025-12-02') or end<=start:raise RuntimeError('Supported audited-fork-rule window: 2025-05-08 <= start < end <= 2025-12-02 (Prague); end exclusive')
    if end-start<30*86400 and not args.smoke_blocks:raise RuntimeError('At least 30 complete days required')
    if not shutil.which('anvil'):raise RuntimeError('Install official Foundry/Anvil and run forge build first')
    if not pathlib.Path('out/Replay.sol/Replay.json').exists():raise RuntimeError('Run forge build first')
    out=pathlib.Path(args.output);out.mkdir(parents=True,exist_ok=True)
    rpc=RPC(url,str(out/'archive.sqlite'),args.rpc_budget)
    if int(rpc.call('eth_chainId',[],False),16)!=1:raise RuntimeError('Ethereum mainnet only')
    latest=rpc.block(int(rpc.call('eth_blockNumber',[],False),16))
    if end>int(latest['timestamp'],16)-86400:raise RuntimeError('Use a fully historical range ending >=24h before latest head')
    first=rpc.at_time(start);last=rpc.at_time(end)-1
    if args.smoke_blocks:last=min(last,first+args.smoke_blocks-1)
    fx=parse_fx(pathlib.Path(args.fx_csv).read_text(encoding='utf-8-sig')) if args.fx_csv else fx_download(args.start,args.end,out)
    fx_at(fx,args.start);fx_at(fx,day(int(rpc.block(last)['timestamp'],16)))
    market=Market(rpc,first-1);initial=market.snapshot(first-1)
    ref_cap=int(args.capital_nok*0.8*.997/fx_at(fx,args.start)/initial['usdc_usd']*1e6)
    artifact=pathlib.Path('out/Replay.sol/Replay.json').read_bytes()
    manifest=dict(schema=1,start=args.start,end_exclusive=args.end,first=first,last=last,capital_nok=args.capital_nok,pools=market.pools,reference_own_usdc=ref_cap,fx=fx,smoke_only=bool(args.smoke_blocks),status='INCOMPLETE',complete=False,blocks=last-first+1,artifact_sha256=hashlib.sha256(artifact).hexdigest(),collector_sha256=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in list(pathlib.Path('.').glob('*.py'))+list(pathlib.Path('contracts').glob('*.sol'))},scope='USDC-WETH; Uniswap V2, Sushi V2, Uniswap V3 500/3000; Ethereum mainnet',minimum_pool_age_days=30,minimum_pool_depth_usd=1000000,own_cap_fractions=[.25,.5,.75,1],flash_cap_usdc=10000000)
    mp=out/'manifest.json';rows_path=out/'blocks.jsonl'
    if mp.exists():
        old=json.loads(mp.read_text())
        for key in ['start','end_exclusive','first','last','capital_nok','artifact_sha256','collector_sha256','source_sha256']:
            if old[key]!=manifest[key]:raise RuntimeError('Resume configuration differs; choose a new --output directory')
    completed={}
    if rows_path.exists():
        # Discard only a partial final line after process interruption; preserve complete rows.
        raw=rows_path.read_bytes();lines=raw.splitlines(keepends=True);valid=[]
        for i,line in enumerate(lines):
            try:r=json.loads(line)
            except json.JSONDecodeError:
                if i==len(lines)-1 and not line.endswith(b'\n'):break
                raise
            completed[r['block']]=r;valid.append(line if line.endswith(b'\n') else line+b'\n')
        if len(valid)!=len(lines):rows_path.write_bytes(b''.join(valid))
    mp.write_text(json.dumps(manifest,indent=2));fork=Fork(url)
    try:
        for b in range(first,last+1):
            if b in completed:continue
            p=b-1;prev=rpc.block(p);block=rpc.block(b)
            if block['parentHash']!=prev['hash']:raise RuntimeError('Reorg/inconsistent archive data')
            if next_base(prev)!=int(block['baseFeePerGas'],16):raise RuntimeError('Unsupported base-fee rules/header inconsistency')
            snap=market.snapshot(p);pred_tip=fee_tip(rpc,p);actual_tip=fee_tip(rpc,b)
            simblock=dict(block,timestamp=hex(int(prev['timestamp'],16)+12),miner=prev['miner'],priorityFeeWei=pred_tip)
            row=dict(block=b,hash=block['hash'],parent=prev['hash'],timestamp=int(block['timestamp'],16),day=day(int(block['timestamp'],16)),state_block=p,base_wei=int(block['baseFeePerGas'],16),tip_prior_wei=pred_tip,tip_current_measured_wei=actual_tip,tip_prior_source=rpc.priority_fee_sources[p],tip_current_source=rpc.priority_fee_sources[b],snapshot=snap,candidates=[],screen_positive=0,evm_rejected=0)
            for flash in [True,False]:
                for a in range(4):
                    for z in range(4):
                        if a==z:continue
                        caps=[10_000_000*10**6] if flash else [int(ref_cap*f) for f in [.25,.5,.75,1]]
                        seen=set()
                        for cap in caps:
                            frontier=market.optimize(a,z,p,snap,flash,cap)
                            for c in frontier or []:
                                if c['amount'] in seen:continue
                                seen.add(c['amount']);row['screen_positive']+=1
                                # Full transaction in b's environment, state at END OF b-1; no future reserves.
                                sim=fork.execute(p,simblock,c,flash)
                                if not sim['ok']:
                                    if sim['revert_reason']!='minProfit':raise RuntimeError('Unexpected fork failure: '+str(sim['revert_reason']))
                                    row['evm_rejected']+=1;continue
                                failed=fork.execute(p,simblock,c,flash,force_revert=True)
                                if failed['ok'] or failed['revert_reason']!='minProfit' or failed['gas']>=1800000:raise RuntimeError('Invalid forced-revert gas measurement')
                                # Verify contract minProfit boundary, not merely a Python profitability filter.
                                guarded=fork.execute(p,simblock,c,flash,min_profit=sim['profit'])
                                if not guarded['ok'] or guarded['profit']!=sim['profit']:raise RuntimeError('minProfit simulation inconsistent')
                                comp=market.competition(b,a,z)
                                c.update(mode='A' if flash else 'B',profit_usdc=sim['profit']/1e6,gas=guarded['gas'],revert_gas=failed['gas'],competition=comp)
                                row['candidates'].append(c)
            with rows_path.open('a',encoding='utf-8') as f:f.write(json.dumps(row,separators=(',',':'))+'\n');f.flush();os.fsync(f.fileno())
            completed[b]=row
            if (b-first)%100==0:print(f'{b-first+1}/{last-first+1} blocks; upstream uncached calls this invocation={rpc.calls}',flush=True)
        manifest['complete']=len(completed)==last-first+1
        manifest['status']='SMOKE_ONLY' if args.smoke_blocks else 'COLLECTED'
        manifest['uncached_rpc_this_invocation']=rpc.calls
        mp.write_text(json.dumps(manifest,indent=2))
        print('Collection complete. This is not yet a profitability result. Run analyze.py.')
    except Exception:
        manifest['status']='INCOMPLETE';manifest['completed_blocks']=len(completed);mp.write_text(json.dumps(manifest,indent=2));raise
    finally:fork.close()
if __name__=='__main__':
    try:main()
    except (RPCError,BudgetStop,RuntimeError,ValueError,FileNotFoundError) as e:print(type(e).__name__+': '+str(e),file=sys.stderr);sys.exit(2)
