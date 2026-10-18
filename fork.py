"""All mutations target a fresh, self-started loopback Anvil, never the archive RPC."""
import subprocess,tempfile,socket,time,json,pathlib,urllib.parse
from chain import *
from market import USDC
HARNESS='0x1000000000000000000000000000000000000001'
SENDER='0x1000000000000000000000000000000000000002'
OUTCOME=topic('Outcome(uint256)')
class Fork:
    def __init__(self,upstream,artifact='out/Replay.sol/Replay.json'):
        self.upstream=upstream
        self.code=json.loads(pathlib.Path(artifact).read_text())['deployedBytecode']['object']
        if not self.code.startswith('0x'):self.code='0x'+self.code
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        self.url=f'http://127.0.0.1:{port}';self.rpc=RPC(self.url,budget=10**12)
        self.log=tempfile.TemporaryFile()
        # No real key, fork URL or secret in command arguments/logs.
        self.proc=subprocess.Popen(['anvil','--host','127.0.0.1','--port',str(port),'--chain-id','31337','--hardfork','prague','--no-mining','--silent'],stdout=self.log,stderr=self.log)
        for _ in range(100):
            if self.proc.poll() is not None:raise RuntimeError('Anvil failed to start')
            try:
                if self.rpc._request('web3_clientVersion',[]):break
            except Exception:time.sleep(.1)
        else:raise RuntimeError('Anvil start timeout')
        self.slot=None
    def call(self,m,p):
        if urllib.parse.urlsplit(self.url).hostname!='127.0.0.1':raise RuntimeError('Nonlocal mutation forbidden')
        version=self.rpc._request('web3_clientVersion',[])
        chain=int(self.rpc.call('eth_chainId',[],False),16)
        if 'anvil' not in version.lower() or chain!=31337:raise RuntimeError('Not our isolated Anvil chain')
        return self.rpc._request(m,p)
    def reset(self,p,block):
        self.call('anvil_reset',[{'forking':{'jsonRpcUrl':self.upstream,'blockNumber':p}}])
        if self.rpc.call('eth_getCode',[HARNESS,'latest'])!='0x':raise RuntimeError('Harness address collision')
        self.call('anvil_setCode',[HARNESS,self.code]);self.call('anvil_setBalance',[SENDER,hex(10**24)])
        self.call('anvil_impersonateAccount',[SENDER])
        self.call('evm_setNextBlockTimestamp',[int(block['timestamp'],16)])
        self.call('anvil_setNextBlockBaseFeePerGas',[block['baseFeePerGas']])
        self.call('anvil_setCoinbase',[block['miner']])
    def fund(self,amount):
        # Test mapping location on a disposable fork; never change upstream token storage.
        slots=[self.slot] if self.slot is not None else range(100)
        for slot in slots:
            key='0x'+keccak(bytes.fromhex(word(HARNESS)+word(slot))).hex()
            prior=self.rpc.call('eth_getStorageAt',[USDC,key,'latest'],False)
            self.call('anvil_setStorageAt',[USDC,key,'0x'+word(amount)])
            result=self.rpc.ethcall(USDC,'balanceOf(address)',HARNESS,block=int(self.rpc.call('eth_blockNumber',[],False),16))
            if result[0]==amount:self.slot=slot;return
            self.call('anvil_setStorageAt',[USDC,key,prior])
        raise RuntimeError('Cannot safely locate USDC simulation balance mapping')
    def execute(self,p,b,candidate,flash,min_profit=0,force_revert=False,prefund=0):
        self.reset(p,b)
        if not flash or prefund:self.fund((0 if flash else candidate['amount'])+prefund)
        required=(1<<255) if force_revert else min_profit
        data=encode('run(uint256,uint8,uint8,bool,uint256)',candidate['amount'],candidate['first'],candidate['second'],int(flash),required)
        gas_price=int(b['baseFeePerGas'],16)+int(b['priorityFeeWei'])
        tx=self.call('eth_sendTransaction',[{'from':SENDER,'to':HARNESS,'data':data,'gas':hex(1800000),'gasPrice':hex(gas_price),'value':'0x1'}])
        self.call('evm_mine',[]);receipt=self.rpc.call('eth_getTransactionReceipt',[tx],False)
        if receipt is None:raise RuntimeError('Missing local simulation receipt')
        profit=0
        for l in receipt['logs']:
            if l['address'].lower()==HARNESS and l['topics'][0].lower()==OUTCOME:profit=words(l['data'])[0]
        ok=int(receipt['status'],16)==1;reason=None
        if not ok:
            try:trace=self.call('debug_traceTransaction',[tx,{'tracer':'callTracer'}])
            except RPCError:trace=self.call('debug_traceTransaction',[tx,{'disableStorage':True,'disableMemory':True,'disableStack':True}])
            output=trace.get('returnValue',trace.get('output','')).removeprefix('0x')
            if output.startswith('08c379a0'):
                raw=bytes.fromhex(output[8:]);offset=int.from_bytes(raw[:32],'big');length=int.from_bytes(raw[offset:offset+32],'big')
                reason=raw[offset+32:offset+32+length].decode('utf-8',errors='replace')[:128]
            else:reason='unknown revert: '+output[:8]
        return dict(ok=ok,gas=int(receipt['gasUsed'],16),profit=profit,revert_reason=reason)
    def close(self):
        if self.proc.poll() is None:self.proc.terminate();self.proc.wait(timeout=10)
        self.log.close()
