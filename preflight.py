"""Small guarded archive/local-state replay check, not a historical profit result."""
import argparse,pathlib,sys,shutil
from chain import *
from market import *
from collect import fee_tip
from fork import Fork
from quota import QuotaClient,QuotaGateway,DEFAULT_MAX_CU

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--date',default='2025-06-01')
    ap.add_argument('--max-cu',type=int,default=DEFAULT_MAX_CU);ap.add_argument('--quota-dir',default='.cache/alchemy')
    args=ap.parse_args()
    if not shutil.which('anvil') or not pathlib.Path('out/Replay.sol/Replay.json').exists():
        raise RuntimeError('Local replay tools/artifact are missing. No Alchemy request sent. Do not start preflight before the pilot prerequisites are prepared.')
    load_env()
    with QuotaClient(rpc_url(),args.quota_dir,args.max_cu,max_requests=2000) as meter:
        try:
            rpc=meter.rpc
            if int(rpc.call('eth_chainId',[]),16)!=1:raise RuntimeError('Not Ethereum mainnet')
            b=rpc.at_time(timestamp(args.date));market=Market(rpc,b-1);market.snapshot(b-1);fee_tip(rpc,b-1)
            print('PASS: historical headers, pool age/tokens/fees, state, Aave premium and measured priority-fee data.')
            with QuotaGateway(meter) as gateway:
                fork=Fork(gateway.url)
                try:
                    prev=rpc.block(b-1);block=dict(rpc.block(b),timestamp=hex(int(prev['timestamp'],16)+12),miner=prev['miner'],priorityFeeWei=fee_tip(rpc,b-1))
                    for flash in [True,False]:
                        c=dict(first=0,second=1,amount=100*10**6)
                        try:result=fork.execute(b-1,block,c,flash,force_revert=True,prefund=10*10**6 if flash else 0)
                        finally:meter.raise_if_stopped()
                        if result['ok'] or result['revert_reason']!='minProfit':raise RuntimeError('Local replay did not reach minProfit: '+str(result['revert_reason']))
                        print('PASS: disposable local state replay reaches final minProfit; mode='+('flash' if flash else 'own'))
                finally:fork.close()
            fx_download(args.date,args.date,pathlib.Path('.cache'));print('PASS: historical USD/NOK.')
            print('No deployment or real transaction. This is NOT a one-day or 30-day backtest.')
        finally:
            meter.write_summary();print('BEREGNET cumulative CU estimate:',meter.summary()['estimated_cu_reserved'],'(ANTATTE satser; not billed CU)')
if __name__=='__main__':
    try:main()
    except (RPCError,BudgetStop,RuntimeError,ValueError,FileNotFoundError) as e:print(type(e).__name__+': '+str(e),file=sys.stderr);sys.exit(2)
