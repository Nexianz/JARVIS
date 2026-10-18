"""Local hidden-input configuration + read-only archive test. Never prints endpoint/key."""
import argparse,getpass,os,pathlib,sys,warnings
from chain import RPC,RPCError,load_env,rpc_url,DEFAULT_ALCHEMY_ENDPOINT,priority_fee


def write_config(path,endpoint,key=None):
    if key is None:
        rpc_url({'ETH_RPC_URL':endpoint})
        if any(c in endpoint for c in '\r\n\"\''):raise RuntimeError('Invalid full URL format (redacted).')
        content='# Local secrets. Never commit/share this file.\nETH_RPC_URL='+endpoint+'\n'
    else:
        if any(c in key for c in '\r\n\"\'') or not key.strip() or any(c.isspace() for c in key):
            raise RuntimeError('Invalid key format (redacted).')
        rpc_url({'ALCHEMY_ENDPOINT':endpoint,'ALCHEMY_API_KEY':key})
        content='# Local secrets. Never commit/share this file.\nALCHEMY_ENDPOINT='+endpoint+'\nALCHEMY_API_KEY='+key+'\nETH_RPC_URL=\n'
    try:fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:raise RuntimeError('.env already exists; edit it locally rather than overwriting it.') from None
    with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(content)


def hidden_input(prompt):
    with warnings.catch_warnings():
        warnings.simplefilter('error',getpass.GetPassWarning)
        try:return getpass.getpass(prompt).strip()
        except getpass.GetPassWarning:raise RuntimeError('Hidden input unavailable; edit .env locally instead.') from None


def check():
    load_env();r=RPC(rpc_url(),budget=2000)
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
    priority_fee(r,b)
    print('PASS: historical priority-fee data via '+r.priority_fee_sources[b]+'. No transaction sent.')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--check',action='store_true',help='Read-only RPC check; requires no Foundry/Anvil');a=ap.parse_args()
    if a.check:check();return
    if pathlib.Path('.env').exists():raise RuntimeError('.env already exists. Edit it locally, then run python3 rpc_setup.py --check.')
    print('Use a NEW Alchemy Ethereum Mainnet key; revoke the one in the old ZIP.')
    endpoint=hidden_input('Endpoint template OR full HTTPS URL (hidden; Enter = default): ') or DEFAULT_ALCHEMY_ENDPOINT
    if '{API_KEY}' in endpoint:
        key=hidden_input('New Alchemy API key (hidden): ')
        write_config('.env',endpoint,key)
    else:
        # A full URL already carries any required credentials; do not ask for another key.
        write_config('.env',endpoint)
    print('Saved local .env (ignored by Git). Key/URL not displayed. Run python3 rpc_setup.py --check.')

if __name__=='__main__':
    try:main()
    except (RPCError,RuntimeError,ValueError,OSError) as e:
        if isinstance(e,(RPCError,RuntimeError)):print(str(e),file=sys.stderr)
        else:print('Configuration/check failed: '+type(e).__name__+' (details redacted)',file=sys.stderr)
        sys.exit(2)
