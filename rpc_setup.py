"""Local hidden-input configuration + read-only archive test. Never prints endpoint/key."""
import argparse,getpass,os,pathlib,sys,warnings
from chain import RPC,RPCError,load_env,rpc_url,DEFAULT_ALCHEMY_ENDPOINT


def write_config(path,endpoint,key):
    if any(c in key for c in '\r\n\"\'') or not key.strip() or any(c.isspace() for c in key):
        raise RuntimeError('Invalid key format (redacted).')
    rpc_url({'ALCHEMY_ENDPOINT':endpoint,'ALCHEMY_API_KEY':key})
    content='# Local secrets. Never commit/share this file.\nALCHEMY_ENDPOINT='+endpoint+'\nALCHEMY_API_KEY='+key+'\nETH_RPC_URL=\n'
    try:fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:raise RuntimeError('.env already exists; edit it locally rather than overwriting it.') from None
    with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(content)


def check():
    load_env();r=RPC(rpc_url(),budget=20)
    if int(r.call('eth_chainId',[]),16)!=1:raise RuntimeError('Endpoint is not Ethereum mainnet.')
    print('PASS: Ethereum mainnet connection (chain ID 1).')
    b=23_000_000;tag=hex(b)
    if not r.block(b):raise RuntimeError('Historical block unavailable.')
    factory='0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f'
    usdc='0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48';weth='0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
    from chain import addr
    pair=addr(r.ethcall(factory,'getPair(address,address)',usdc,weth,block=b)[0])
    reserves=r.ethcall(pair,'getReserves()',block=b)
    if len(reserves)!=3 or not reserves[0] or not reserves[1]:raise RuntimeError('Historical pool reserves missing.')
    print('PASS: archive eth_call at explicit historical block 23000000.')
    h=r.call('eth_feeHistory',['0x1',tag,[50]])
    if not h.get('reward'):raise RuntimeError('Historical priority fees missing.')
    print('PASS: historical priority-fee data. No transaction sent.')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--check',action='store_true',help='Read-only RPC check; requires no Foundry/Anvil');a=ap.parse_args()
    if a.check:check();return
    if pathlib.Path('.env').exists():raise RuntimeError('.env already exists. Edit it locally, then run python3 rpc_setup.py --check.')
    print('Use a NEW Alchemy Ethereum Mainnet key; revoke the one in the old ZIP.')
    endpoint=input('Endpoint template [Enter = standard Ethereum mainnet Alchemy]: ').strip() or DEFAULT_ALCHEMY_ENDPOINT
    # Never fall back to echoing a secret in a terminal without hidden-input support.
    with warnings.catch_warnings():
        warnings.simplefilter('error',getpass.GetPassWarning)
        try:key=getpass.getpass('New Alchemy API key (hidden): ').strip()
        except getpass.GetPassWarning:raise RuntimeError('Hidden input unavailable; edit .env locally instead.') from None
    write_config('.env',endpoint,key)
    print('Saved local .env (ignored by Git). Key/URL not displayed. Run python3 rpc_setup.py --check.')

if __name__=='__main__':
    try:main()
    except (RPCError,RuntimeError,ValueError,OSError) as e:
        if isinstance(e,(RPCError,RuntimeError)):print(str(e),file=sys.stderr)
        else:print('Configuration/check failed: '+type(e).__name__+' (details redacted)',file=sys.stderr)
        sys.exit(2)
