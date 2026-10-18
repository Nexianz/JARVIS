"""Deterministic sampling and prior-block Swap-event filter. No next-block look-ahead."""
import json,pathlib,os
from market import SWAP2,SWAP3

def sampled(block,first,every):
    if not isinstance(every,int) or every<1:raise ValueError('--every-n-blocks must be >= 1')
    return (block-first)%every==0

class SwapFilter:
    def __init__(self,rpc,pools,first_state_block,last_state_block,chunk=10):
        if not isinstance(chunk,int) or not 1<=chunk<=10:raise ValueError('--log-chunk-blocks must be 1..10 (bounded for free-tier compatibility)')
        self.rpc=rpc;self.addresses=sorted(p['address'].lower() for p in pools)
        self.first=first_state_block;self.last=last_state_block;self.chunk=chunk;self.chunks={}
    def active(self,state_block):
        if not self.first<=state_block<=self.last:raise ValueError('Swap-filter block outside selected state range')
        start=self.first+(state_block-self.first)//self.chunk*self.chunk;end=min(self.last,start+self.chunk-1)
        if start not in self.chunks:
            logs=self.rpc.call('eth_getLogs',[{'fromBlock':hex(start),'toBlock':hex(end),'address':self.addresses,'topics':[[SWAP2,SWAP3]]}])
            if not isinstance(logs,list):raise ValueError('Missing Swap logs; cannot classify block as inactive')
            active=set();seen=set()
            for log in logs:
                b=int(log['blockNumber'],16)
                if not start<=b<=end or log['address'].lower() not in self.addresses or not log.get('topics') or log['topics'][0].lower() not in (SWAP2,SWAP3) or log.get('removed',False):
                    raise ValueError('Invalid/inconsistent Swap logs')
                identity=(log['transactionHash'],log['logIndex'])
                if identity in seen:raise ValueError('Duplicate Swap log')
                seen.add(identity);active.add(b)
            self.chunks[start]=active
        # Prefetch may contain later events, but classification uses ONLY exactly state_block=b-1.
        return state_block in self.chunks[start]

class Checkpoints:
    def __init__(self,path):
        self.path=pathlib.Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.completed=set();self.counts={}
        if self.path.exists():
            with self.path.open('rb+') as f:
                valid_end=0
                while True:
                    line=f.readline()
                    if not line:break
                    try:r=json.loads(line)
                    except json.JSONDecodeError:
                        if not line.endswith(b'\n') and f.read(1)==b'':f.truncate(valid_end);break
                        raise ValueError('Corrupt checkpoint; refusing to silently skip records')
                    if r['block'] in self.completed:raise ValueError('Duplicate checkpoint block')
                    self.completed.add(r['block']);status=r.get('selection','evaluated');self.counts[status]=self.counts.get(status,0)+1
                    valid_end=f.tell()
                # A complete JSON object without a final newline needs separation before append.
                if valid_end and self.path.stat().st_size==valid_end:
                    f.seek(valid_end-1)
                    if f.read(1)!=b'\n':f.seek(0,2);f.write(b'\n');f.flush();os.fsync(f.fileno())
    def add(self,row):
        if row['block'] in self.completed:raise ValueError('Block already checkpointed')
        with self.path.open('a',encoding='utf-8') as f: f.write(json.dumps(row,separators=(',',':'))+'\n');f.flush();os.fsync(f.fileno())
        self.completed.add(row['block']);status=row.get('selection','evaluated');self.counts[status]=self.counts.get(status,0)+1
