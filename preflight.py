"""Small real archive/fork check, not a historical profit result."""
import argparse,os,pathlib,sys
from chain import *
from market import *
from collect import fee_tip
from fork import Fork

def main():
    a=argparse.ArgumentParser();a.add_argument('--date',default='2025-06-01');args=a.parse_args();load_env()
    url=rpc_url()
    rpc=RPC(url,budget=2000)
    if int(rpc.call('eth_chainId',[]),16)!=1:raise RuntimeError('Not Ethereum mainnet')
    b=rpc.at_time(timestamp(args.date));market=Market(rpc,b-1);s=market.snapshot(b-1);fee_tip(rpc,b-1)
    print('PASS: historical headers, pool age/tokens/fee tiers, reserves/V3 state, Aave premium and gas-weighted priority fee.')
    # A deliberately unprofitable/minProfit-impossible local transaction must get as far as the final guard.
    fork=Fork(url)
    try:
        prev=rpc.block(b-1);block=dict(rpc.block(b),timestamp=hex(int(prev['timestamp'],16)+12),miner=prev['miner'],priorityFeeWei=fee_tip(rpc,b-1))
        for flash in [True,False]:
            c=dict(first=0,second=1,amount=100*10**6)
            result=fork.execute(b-1,block,c,flash,force_revert=True,prefund=10*10**6 if flash else 0)
            if result['ok'] or result['revert_reason']!='minProfit':raise RuntimeError('Full trade did not reach minProfit: '+str(result['revert_reason']))
            print('PASS: full local loan/swap/swap/repay path reaches final minProfit guard; mode='+('flash' if flash else 'own'))
    finally:fork.close()
    fx_download(args.date,args.date,pathlib.Path('.cache'));print('PASS: Norges Bank historical USD/NOK.')
    print('No money moved. Preflight is NOT a 30-day backtest.')
if __name__=='__main__':
    try:main()
    except Exception as e:
        # Prevent unexpected library errors printing credentials. Tracebacks intentionally suppressed.
        if isinstance(e,(RPCError,RuntimeError,ValueError,FileNotFoundError)):print(type(e).__name__+': '+str(e),file=sys.stderr)
        else:print('Preflight failed: '+type(e).__name__+' (details redacted)',file=sys.stderr)
        sys.exit(2)
