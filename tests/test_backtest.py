"""Synthetic unit fixtures ONLY. These never produce the historical report or return charts."""
import unittest,dataclasses,tempfile,pathlib,json,unittest.mock
from chain import *
from market import *
from model import *
from analyze import validate,compact

def fixture():
    row=dict(block=1,state_block=0,day='2025-07-01',timestamp=timestamp('2025-07-01'),base_wei=10**9,tip_prior_wei=10**9,tip_current_measured_wei=100*10**9,
      snapshot=dict(eth_usd=2000,usdc_usd=1,premium_bps=5,state=[[1],[2],[3],[4]]),candidates=[])
    c=dict(mode='A',first=0,second=1,amount=1000*10**6,profit_usdc=100,gas=200000,revert_gas=190000,competition={'same_route_cycle_txs':[]})
    m=dict(capital_nok=5000,fx={'2025-07-01':10})
    return row,c,m
class EncodingTests(unittest.TestCase):
    def test_keccak_ethereum_vectors(self):
        self.assertEqual(keccak(b'').hex(),'c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470')
        self.assertEqual(keccak(b'abc').hex(),'4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45')
    def test_known_selectors(self):
        for sig,expected in [('getPool()','026b1d5f'),('FLASHLOAN_PREMIUM_TOTAL()','074b2e43'),('balanceOf(address)','70a08231'),('quoteExactInputSingle((address,address,uint256,uint24,uint160))','c6a5026a')]:self.assertEqual(encode(sig)[2:10],expected)
    def test_words(self):self.assertEqual(words('0x'+word(USDC)),[int(USDC,16)])
    def test_reject_bad_abi(self):
        with self.assertRaises(ValueError):words('0x123')
    def test_no_remote_mutation(self):
        r=RPC('https://invalid.invalid')
        with self.assertRaises(RPCError):r.call('eth_sendTransaction',[])
    def test_endpoint_not_in_error(self):
        r=RPC('https://invalid.invalid/SECRET')
        with unittest.mock.patch('urllib.request.urlopen',side_effect=urllib.error.URLError('SECRET')),unittest.mock.patch('time.sleep'):
            with self.assertRaises(RPCError) as e:r.call('eth_chainId',[])
        self.assertNotIn('SECRET',str(e.exception))
class DataTests(unittest.TestCase):
    def test_fx_forward_only(self):
        self.assertEqual(fx_at({'2025-07-01':10,'2025-07-03':20},'2025-07-02'),10)
        with self.assertRaises(ValueError):fx_at({'2025-07-03':20},'2025-07-01')
    def test_fx_stale(self):
        with self.assertRaises(ValueError):fx_at({'2025-07-01':10},'2025-07-10')
    def test_csv_fx(self):self.assertEqual(parse_fx('TIME_PERIOD,OBS_VALUE\n2025-07-01,10.1\n'),{'2025-07-01':10.1})
    def test_base_fee_eip1559(self):
        self.assertEqual(next_base(dict(baseFeePerGas=hex(1000),gasUsed=hex(200),gasLimit=hex(200))),1125)
        self.assertEqual(next_base(dict(baseFeePerGas=hex(1000),gasUsed=hex(0),gasLimit=hex(200))),875)
    def test_incomplete_report_refused(self):
        with tempfile.TemporaryDirectory() as d:
            pathlib.Path(d,'manifest.json').write_text(json.dumps({'complete':False}))
            with self.assertRaises(ValueError):validate(d)
    def test_smoke_report_refused(self):
        with tempfile.TemporaryDirectory() as d:
            pathlib.Path(d,'manifest.json').write_text(json.dumps({'complete':True,'status':'SMOKE_ONLY','smoke_only':True}))
            with self.assertRaises(ValueError):validate(d)
class RiskTests(unittest.TestCase):
    def test_daily_prospective_kill(self):
        s=Assumptions(maximum_daily_loss_nok=10,maximum_weekly_loss_nok=30)
        r=Risk(s);r.record(10000,-8,True);self.assertFalse(r.allow(10001,3,1,1));self.assertTrue(r.allow(10001,2,1,1))
    def test_hourly_failures_expire(self):
        r=Risk(Assumptions(maximum_failures_hour=2));r.record(10000,-1,True);r.record(10001,-1,True)
        self.assertFalse(r.allow(10002,1,1,1));self.assertTrue(r.allow(13601,1,1,1))
    def test_gas_caps(self):
        r=Risk(Assumptions());self.assertFalse(r.allow(10000,1,31,1));self.assertFalse(r.allow(10000,1,1,101))
    def test_weekly_kill_survives_midnight(self):
        r=Risk(Assumptions(maximum_daily_loss_nok=10,maximum_weekly_loss_nok=10))
        t=timestamp('2025-07-01');r.record(t,-8,False);self.assertFalse(r.allow(t+86400,3,1,1))
    def test_private_lost_bundle_zero_gas(self):
        row,c,m=fixture();c['competition']['same_route_cycle_txs']=['0xsynthetic'];row['candidates']=[c]
        s=dataclasses.replace(Assumptions(),minimum_net_nok=0,margin_fraction=0)
        r=simulate([row],m,s);self.assertEqual(r['gas_eth'],0);self.assertEqual(r['counts']['taken_by_other_proxy'],1);self.assertNotIn('wins',r['counts'])
    def test_public_lost_bundle_pays_revert_no_bid(self):
        row,c,m=fixture();c['competition']['same_route_cycle_txs']=['0xsynthetic'];row['candidates']=[c]
        s=dataclasses.replace(Assumptions(),public_inclusion=1.,minimum_net_nok=0,margin_fraction=0)
        r=simulate([row],m,s,channel='public');self.assertGreater(r['gas_eth'],0);self.assertEqual(r['builder_bid_eth'],0);self.assertEqual(r['counts']['failed'],1)
    def test_current_tip_not_used_for_decisions(self):
        row,c,m=fixture();s=Assumptions();a=economics(c,row,m['fx'],s);row['tip_current_measured_wei']=10**20
        self.assertEqual(a,economics(c,row,m['fx'],s))
    def test_higher_builder_bid_reduces_retained_profit(self):
        row,c,m=fixture();s=Assumptions();self.assertGreater(economics(c,row,m['fx'],dataclasses.replace(s,bid=.8))['net'],economics(c,row,m['fx'],dataclasses.replace(s,bid=.99))['net'])
    def test_min_profit_haircut_causes_revert(self):
        row,c,m=fixture();row['candidates']=[c];s=dataclasses.replace(Assumptions(),private_inclusion=1.,failure=0.,adverse_profit_haircut=.99,minimum_net_nok=0,margin_fraction=0)
        r=simulate([row],m,s);self.assertEqual(r['counts'].get('failed'),1)
    def test_cannot_harvest_identical_pool_state_twice(self):
        row,c,m=fixture();row['candidates']=[c];r2=dict(row,block=2,timestamp=row['timestamp']+12)
        s=dataclasses.replace(Assumptions(),private_inclusion=1.,failure=0.,adverse_profit_haircut=0.,minimum_net_nok=0,margin_fraction=0)
        r=simulate([row,r2],m,s);self.assertEqual(r['counts'].get('wins'),1)
    def test_own_capital_affordability(self):
        row,c,m=fixture();c['mode']='B';row['candidates']=[c];r=simulate([row],m,Assumptions(),mode='B');self.assertEqual(r['counts'].get('attempts',0),0)
    def test_no_trade_exposure_not_arbitrage_profit(self):
        row,c,m=fixture();r2=dict(row,block=2,timestamp=row['timestamp']+12,snapshot=dict(row['snapshot'],eth_usd=4000))
        r=simulate([row,r2],m,Assumptions());self.assertGreater(r['total_return_nok'],0);self.assertEqual(r['incremental_vs_hold_nok'],0);self.assertLess(r['strategy_pnl_trade_fx_nok'],0)

class MarketLogicTests(unittest.TestCase):
    def test_swap_competition_requires_both_legs_same_transaction(self):
        class Fake:
            logs=[]
            def call(self,*a):return self.logs
        r=Fake();m=object.__new__(Market);m.rpc=r;m.pools=[{'address':'0x01','usdc0':True},{'address':'0x02','usdc0':True}]
        def log(pool,tx,data):return dict(address=pool,transactionHash=tx,topics=[SWAP2],data='0x'+''.join(word(x) for x in data))
        r.logs=[log('0x01','a',[100,0,0,50]),log('0x02','a',[0,50,105,0])]
        self.assertEqual(m.competition(1,0,1)['same_route_cycle_txs'],['a'])
        r.logs[1]['transactionHash']='b';self.assertEqual(m.competition(1,0,1)['same_route_cycle_txs'],[])
    def test_size_search_includes_price_impact_optimum(self):
        class Fake:
            def ethcall(self,address,*a,**kw):return reserves[int(address)]
        reserves=[[1_000_000*10**6,500*10**18],[1_050_000*10**6,500*10**18]]
        m=object.__new__(Market);m.rpc=Fake();m.min_depth=1;m.pools=[{'address':'0','usdc0':True},{'address':'1','usdc0':True}]
        s=dict(usdc_usd=1,state=reserves,depths=[1e6,1.05e6],flash_liquidity=10**15,premium_bps=5)
        frontier=m.optimize(0,1,1,s,False,100000*10**6)
        best=max(frontier,key=lambda c:c['quoted_profit'])
        def gain(x):return m.quote(1,m.quote(0,x,True,1),False,1)-x
        brute=max(gain(x*10**6) for x in range(1,30000,10))
        self.assertGreaterEqual(best['quoted_profit'],brute-10)
        self.assertLess(best['amount'],100000*10**6)
    def test_unprofitable_marginal_price_skips_quotes(self):
        class Fake:
            def ethcall(self,*a,**kw):raise AssertionError('No expensive RPC necessary')
        m=object.__new__(Market);m.rpc=Fake();m.min_depth=1;m.pools=[{'usdc0':True},{'usdc0':True}]
        s=dict(state=[[1000,1000],[1000,1000]],premium_bps=5,depths=[1000,1000],usdc_usd=1)
        self.assertIsNone(m.optimize(0,1,1,s,True,10**9))

class ConfigurationTests(unittest.TestCase):
    def test_separate_key_and_endpoint(self):
        self.assertEqual(rpc_url({'ALCHEMY_API_KEY':'synthetic_key'}),'https://eth-mainnet.g.alchemy.com/v2/synthetic_key')
    def test_full_url_takes_precedence(self):
        self.assertEqual(rpc_url({'ETH_RPC_URL':'https://archive.example/rpc','ALCHEMY_API_KEY':'unused'}),'https://archive.example/rpc')
    def test_missing_secret_is_not_printed(self):
        with self.assertRaises(RuntimeError):rpc_url({})
    def test_reject_key_to_wrong_host(self):
        with self.assertRaises(RuntimeError) as e:rpc_url({'ALCHEMY_API_KEY':'synthetic_secret','ALCHEMY_ENDPOINT':'https://other.example/{API_KEY}'})
        self.assertNotIn('synthetic_secret',str(e.exception))
    def test_reject_non_https(self):
        with self.assertRaises(RuntimeError):rpc_url({'ETH_RPC_URL':'http://example.invalid/rpc'})
    def test_setup_refuses_to_overwrite(self):
        from rpc_setup import write_config
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'.env';p.write_text('preserved')
            with self.assertRaises(RuntimeError):write_config(p,DEFAULT_ALCHEMY_ENDPOINT,'synthetic_key')
            self.assertEqual(p.read_text(),'preserved')
    def test_setup_saves_local_config(self):
        from rpc_setup import write_config
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'.env';write_config(p,DEFAULT_ALCHEMY_ENDPOINT,'synthetic_key')
            self.assertIn('ALCHEMY_API_KEY=synthetic_key',p.read_text())
    def test_http_error_is_actionable_and_redacted(self):
        r=RPC('https://example.invalid/SECRET')
        error=urllib.error.HTTPError('https://example.invalid/SECRET',403,'Forbidden',{},None)
        with unittest.mock.patch('urllib.request.urlopen',side_effect=error):
            with self.assertRaises(RPCError) as e:r.call('eth_chainId',[])
        self.assertIn('HTTP 403',str(e.exception));self.assertNotIn('SECRET',str(e.exception))

class FullURLSetupTests(unittest.TestCase):
    def test_full_url_is_saved_without_separate_key(self):
        from rpc_setup import write_config
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'.env';write_config(p,'https://eth-mainnet.g.alchemy.com/v2/synthetic_key')
            self.assertEqual(p.read_text().splitlines()[-1],'ETH_RPC_URL=https://eth-mainnet.g.alchemy.com/v2/synthetic_key')
    def test_full_url_cannot_overwrite_existing_env(self):
        from rpc_setup import write_config
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'.env';p.write_text('preserved')
            with self.assertRaises(RuntimeError):write_config(p,'https://example.invalid/rpc')
            self.assertEqual(p.read_text(),'preserved')
    def test_wizard_full_url_needs_only_one_hidden_input(self):
        import rpc_setup,io
        url='https://eth-mainnet.g.alchemy.com/v2/synthetic_secret'
        with unittest.mock.patch('sys.argv',['rpc_setup.py']),unittest.mock.patch('pathlib.Path.exists',return_value=False),unittest.mock.patch('getpass.getpass',return_value=url) as prompt,unittest.mock.patch('rpc_setup.write_config') as save,unittest.mock.patch('sys.stdout',new_callable=io.StringIO) as output:
            rpc_setup.main();self.assertEqual(prompt.call_count,1);save.assert_called_once_with('.env',url);self.assertNotIn('synthetic_secret',output.getvalue())
    def test_wizard_default_requests_separate_key(self):
        import rpc_setup,io
        with unittest.mock.patch('sys.argv',['rpc_setup.py']),unittest.mock.patch('pathlib.Path.exists',return_value=False),unittest.mock.patch('getpass.getpass',side_effect=['','synthetic_key']) as prompt,unittest.mock.patch('rpc_setup.write_config') as save,unittest.mock.patch('sys.stdout',new_callable=io.StringIO):
            rpc_setup.main();self.assertEqual(prompt.call_count,2);save.assert_called_once_with('.env',DEFAULT_ALCHEMY_ENDPOINT,'synthetic_key')

if __name__=='__main__':unittest.main()
