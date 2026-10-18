"""Offline quota/cache/gateway tests. Synthetic RPC replies, no Alchemy access or results."""
import io,json,pathlib,tempfile,unittest,urllib.request,urllib.error
from quota import QuotaClient,QuotaGateway,QuotaStop,UncertainRequest,DEFAULT_MAX_CU
from chain import RPCError
from selection import Checkpoints,SwapFilter,sampled
from market import SWAP2

class Transport:
    def __init__(self):self.requests=[];self.fail=None
    def __call__(self,request,timeout):
        data=json.loads(request.data);self.requests.append(data)
        if self.fail:raise self.fail
        m=data['method'];p=data['params']
        if m in ('eth_getBlockByNumber','eth_getBlockByHash'):
            n=int(p[0],16) if m.endswith('Number') else 10
            result={'number':hex(n),'hash':hex(1000+n),'transactions':[{'hash':'0xtx'}]}
        elif m=='eth_blockNumber':result='0x100'
        elif m=='eth_getLogs':result=[]
        else:result='0x1'
        return io.BytesIO(json.dumps({'jsonrpc':'2.0','id':1,'result':result}).encode())
class QuotaTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.transport=Transport()
    def tearDown(self):self.tmp.cleanup()
    def client(self,**kw):return QuotaClient('https://example.invalid/SECRET_KEY',self.tmp.name,opener=self.transport,**kw)
    def test_default_is_five_percent(self):self.assertEqual(DEFAULT_MAX_CU,1500000)
    def test_preflight_reservation_stops_before_overspend(self):
        with self.client(max_cu=51) as q:
            with self.assertRaises(QuotaStop):q.rpc.call('eth_call',[{},'0xa'])
            self.assertEqual(self.transport.requests,[]);self.assertEqual(q.summary()['estimated_cu_reserved'],0)
    def test_exact_limit_then_no_further_network_call(self):
        with self.client(max_cu=52) as q:
            q.rpc.call('eth_call',[{'to':'0x01'},'0xa'])
            with self.assertRaises(QuotaStop):q.rpc.call('eth_getCode',['0x02','0xa'])
            self.assertEqual(len(self.transport.requests),1);self.assertEqual(q.summary()['estimated_cu_reserved'],52)
    def test_budget_persists_and_cache_hit_costs_zero_after_limit(self):
        args=[{'to':'0x01'},'0xa']
        with self.client(max_cu=52) as q:q.rpc.call('eth_call',args)
        with self.client(max_cu=52) as q:
            self.assertEqual(q.rpc.call('eth_call',args),'0x1')
            self.assertEqual(q.summary()['estimated_cu_this_invocation'],0)
            with self.assertRaises(QuotaStop):q.rpc.call('eth_getCode',['0x02','0xa'])
        self.assertEqual(len(self.transport.requests),1)
    def test_block_download_once_for_number_hash_full_and_header_views(self):
        with self.client() as q:
            header=q.rpc.block(10);self.assertEqual(header['transactions'],['0xtx'])
            full=q.rpc.call('eth_getBlockByNumber',['0xa',True]);self.assertIsInstance(full['transactions'][0],dict)
            q.rpc.call('eth_getBlockByHash',[header['hash'],False])
        with self.client() as q:q.rpc.block(10)
        self.assertEqual(len(self.transport.requests),1)
        self.assertEqual(self.transport.requests[0]['params'],['0xa',True])
    def test_cross_client_cache_race_does_not_download_block_twice(self):
        with self.client() as a,self.client() as b:
            reserve=b._reserve
            def raced(*args,**kwargs):
                a.rpc.block(10)  # Another process finishes after b's initial cache lookup.
                return reserve(*args,**kwargs)
            b._reserve=raced;b.rpc.block(10)
            self.assertEqual(len(self.transport.requests),1)
            self.assertEqual(b.summary()['estimated_cu_reserved'],32)
    def test_chain_identity_is_rechecked_after_reopening_not_trusted_from_disk(self):
        with self.client() as q:q.rpc.call('eth_chainId',[]);q.rpc.call('eth_chainId',[])
        with self.client() as q:q.rpc.call('eth_chainId',[])
        self.assertEqual(len(self.transport.requests),2)
    def test_every_known_failed_attempt_is_counted_without_automatic_retry(self):
        self.transport.fail=urllib.error.HTTPError('https://example.invalid/SECRET_KEY',503,'SECRET_KEY',{},None)
        with self.client() as q:
            for _ in range(2):
                with self.assertRaises(RPCError) as error:q.rpc.call('eth_feeHistory',['0x1','0xa',[50]])
                self.assertNotIn('SECRET_KEY',str(error.exception))
            self.assertEqual(q.summary()['estimated_cu_reserved'],40)
            self.assertEqual(q.summary()['by_method']['eth_feeHistory']['failed'],2)
        self.assertEqual(len(self.transport.requests),2)
    def test_timeout_does_not_silently_repeat_on_resume(self):
        self.transport.fail=urllib.error.URLError('SECRET_KEY')
        with self.client() as q:
            with self.assertRaises(UncertainRequest):q.rpc.call('eth_getCode',['0x01','0xa'])
        self.transport.fail=None
        with self.client() as q:
            with self.assertRaises(UncertainRequest):q.rpc.call('eth_getCode',['0x01','0xa'])
            self.assertEqual(q.summary()['estimated_cu_reserved'],38)
        self.assertEqual(len(self.transport.requests),1)
    def test_explicit_uncertain_retry_keeps_both_reservations(self):
        self.transport.fail=urllib.error.URLError('SECRET_KEY')
        with self.client() as q:
            with self.assertRaises(UncertainRequest):q.rpc.call('eth_getCode',['0x01','0xa'])
        self.transport.fail=None
        with self.client(retry_uncertain=True) as q:
            q.rpc.call('eth_getCode',['0x01','0xa']);self.assertEqual(q.summary()['estimated_cu_reserved'],76)
    def test_unknown_or_mutating_method_cannot_bypass_guard(self):
        with self.client() as q:
            for m in ('eth_sendTransaction','eth_sendRawTransaction','debug_traceCall','unknown'):
                with self.assertRaises(RPCError):q.rpc.call(m,[])
        self.assertEqual(self.transport.requests,[])
    def test_gateway_and_python_share_cache_and_limit(self):
        with self.client(max_cu=52) as q,QuotaGateway(q) as gateway:
            payload={'jsonrpc':'2.0','id':1,'method':'eth_call','params':[{'to':'0x01'},'0xa']}
            req=urllib.request.Request(gateway.url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
            open_local=urllib.request.build_opener(urllib.request.ProxyHandler({})).open
            with open_local(req) as response:self.assertEqual(json.load(response)['result'],'0x1')
            self.assertEqual(q.rpc.call('eth_call',payload['params']),'0x1')
            payload['params'][0]['to']='0x02';req=urllib.request.Request(gateway.url,data=json.dumps(payload).encode())
            with open_local(req) as response:self.assertEqual(json.load(response)['error']['code'],-32098)
            self.assertEqual(len(self.transport.requests),1)
    def test_changed_prices_cannot_silently_reprice_existing_ledger(self):
        with self.client() as q:profile=dict(q.profile)
        profile['safety_multiplier']=3;p=pathlib.Path(self.tmp.name)/'profile.json';p.write_text(json.dumps(profile))
        with self.assertRaises(ValueError):self.client(costs_path=p)
    def test_summary_and_database_do_not_contain_endpoint_or_key(self):
        with self.client() as q:q.rpc.call('eth_getCode',['0x01','0xa'])
        for p in pathlib.Path(self.tmp.name).iterdir():
            if p.is_file():self.assertNotIn(b'SECRET_KEY',p.read_bytes())
    def test_cache_setting_cannot_disable_the_guard(self):
        with self.client(max_cu=51) as q:
            with self.assertRaises(QuotaStop):q.rpc.call('eth_call',[{},'0xa'],False)
        self.assertEqual(self.transport.requests,[])
    def test_global_stop_does_not_allow_a_cheaper_method_after_refusal(self):
        with self.client(max_cu=20) as q:
            with self.assertRaises(QuotaStop):q.rpc.call('eth_call',[{},'0xa'])
            with self.assertRaises(QuotaStop):q.rpc.call('eth_blockNumber',[])
        self.assertEqual(self.transport.requests,[])

class SelectionTests(unittest.TestCase):
    def test_deterministic_sampling(self):
        self.assertEqual([b for b in range(100,131) if sampled(b,100,10)],[100,110,120,130])
    def test_filter_only_looks_at_prior_state_block_despite_prefetch(self):
        class Fake:
            calls=0
            def call(self,*args):
                self.calls+=1
                return [{'blockNumber':hex(105),'address':'0xpool','topics':[SWAP2],'transactionHash':'0xt','logIndex':'0x0'}]
        rpc=Fake();f=SwapFilter(rpc,[{'address':'0xpool'}],100,119)
        self.assertFalse(f.active(104));self.assertTrue(f.active(105));self.assertFalse(f.active(106));self.assertEqual(rpc.calls,1)
    def test_bad_logs_stop_instead_of_implying_no_activity(self):
        class Fake:
            def call(self,*args):return None
        with self.assertRaises(ValueError):SwapFilter(Fake(),[{'address':'0xpool'}],100,119).active(100)
    def test_checkpoints_resume_without_reprocessing_and_repair_partial_tail(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'blocks.jsonl';c=Checkpoints(p);c.add({'block':100,'selection':'sampling_skipped'})
            with p.open('ab') as f:f.write(b'{"block":')
            resumed=Checkpoints(p);self.assertEqual(resumed.completed,{100});resumed.add({'block':101,'selection':'no_prior_swap'})
            self.assertEqual(Checkpoints(p).completed,{100,101})
    def test_valid_last_row_without_newline_remains_separate(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'blocks.jsonl';p.write_text('{"block":100}')
            c=Checkpoints(p);c.add({'block':101});self.assertEqual(Checkpoints(p).completed,{100,101})

if __name__=='__main__':unittest.main()
