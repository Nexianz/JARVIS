"""Durable, estimated-CU guard for ALL historical reads, including Anvil's upstream reads.
No real transactions, keys in storage/logs, or unmetered upstream fallback.
"""
import contextlib
import hashlib
import http.server
import json
import os
import pathlib
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from chain import RPC, RPCError, BudgetStop

DEFAULT_MAX_CU = 30_000_000 * 5 // 100
class QuotaStop(BudgetStop): pass
class UncertainRequest(RPCError): pass

class QuotaClient:
    def __init__(self, url, directory='.cache/alchemy', max_cu=DEFAULT_MAX_CU,
                 costs_path=None, opener=None, max_requests=100000, retry_uncertain=False):
        if not isinstance(max_cu, int) or max_cu <= 0:raise ValueError('--max-cu must be a positive integer')
        self.url=url  # Memory only: never part of a cache key, log, summary or exception.
        self.folder=pathlib.Path(directory);self.folder.mkdir(parents=True,exist_ok=True)
        self.profile=json.loads(pathlib.Path(costs_path or pathlib.Path(__file__).with_name('cu_costs.json')).read_text())
        factor=self.profile['safety_multiplier'];rates=self.profile['methods']
        if not isinstance(factor,int) or factor<1 or not rates or any(not isinstance(v,int) or v<0 for v in rates.values()):
            raise ValueError('Invalid CU estimate profile')
        self.costs={k:v*factor for k,v in rates.items()}
        self.profile_hash=hashlib.sha256(json.dumps(self.profile,sort_keys=True).encode()).hexdigest()
        self.max_cu=max_cu;self.max_requests=max_requests;self.invocation_requests=0
        self.cache_hits=0;self.retry_uncertain=retry_uncertain;self.stopped=None
        self.opener=opener or urllib.request.urlopen;self.lock=threading.RLock()
        self.db=sqlite3.connect(self.folder/'rpc.sqlite',check_same_thread=False,timeout=30)
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY,v TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY,v TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS blocks (n INTEGER PRIMARY KEY,h TEXT UNIQUE NOT NULL,v TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY,k TEXT NOT NULL,method TEXT NOT NULL,cu INTEGER NOT NULL,status TEXT NOT NULL,at REAL NOT NULL);
          CREATE INDEX IF NOT EXISTS attempts_key ON attempts(k,status);
        ''')
        saved=self.db.execute("SELECT v FROM meta WHERE k='profile'").fetchone()
        if saved and saved[0]!=self.profile_hash:
            self.db.close();raise ValueError('CU profile changed. Existing budget ledger must not be silently repriced.')
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('profile',?)",(self.profile_hash,));self.db.commit()
        self.start_cu=self._used();self.rpc=GuardedRPC(self);self.head=None;self.session_metadata={}
        self.write_summary()
    def _used(self):return self.db.execute('SELECT COALESCE(SUM(cu),0) FROM attempts').fetchone()[0]
    def summary(self):
        with self.lock:
            rows=self.db.execute('SELECT method,COUNT(*),SUM(cu),SUM(status=\'success\'),SUM(status=\'failed\'),SUM(status IN (\'pending\',\'unknown-retried\')) FROM attempts GROUP BY method ORDER BY method').fetchall()
            used=sum(r[2] for r in rows)
            return dict(label='BEREGNET CU-estimat fra ANTATTE satser; ikke fakturert CU',
                        profile=self.profile,estimated_cu_reserved=used,max_cu=self.max_cu,
                        estimated_cu_this_invocation=used-self.start_cu,remaining_estimated_cu=max(0,self.max_cu-used),
                        attempt_count_label='MÅLT lokalt: reserverte nettverksforsøk, inkludert feil/ukjent levering',
                        cache_hits_this_invocation=self.cache_hits,stop_reason=self.stopped,
                        by_method={r[0]:dict(attempts=r[1],estimated_cu=r[2],successful=r[3],failed=r[4],uncertain=r[5],estimated_cu_per_attempt=self.costs[r[0]]) for r in rows})
    def write_summary(self):
        with self.lock:
            target=self.folder/'cu-summary.json';tmp=target.with_name(f'cu-summary.{os.getpid()}.{threading.get_ident()}.tmp')
            with tmp.open('w',encoding='utf-8') as f:json.dump(self.summary(),f,indent=2,ensure_ascii=False);f.flush();os.fsync(f.fileno())
            os.replace(tmp,target)
    def raise_if_stopped(self):
        if self.stopped:raise QuotaStop(self.stopped)
    def _key(self,method,params):return hashlib.sha256(json.dumps(['ethereum-mainnet',method,params],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    def _immutable(self,method,params):
        if method in ('eth_chainId','net_version','eth_blockNumber'):return False
        if method in ('eth_getTransactionReceipt','eth_getTransactionByHash'):return True
        if method=='eth_getLogs':
            q=params[0]
            return bool(q.get('blockHash')) or all(isinstance(q.get(k),str) and q[k].startswith('0x') for k in ('fromBlock','toBlock'))
        if method=='eth_feeHistory':return len(params)>1 and isinstance(params[1],str) and params[1].startswith('0x')
        if method=='eth_getBlockReceipts':return bool(params) and isinstance(params[0],str) and params[0].startswith('0x')
        tag=params[-1] if params else None
        return isinstance(tag,str) and tag.startswith('0x') or isinstance(tag,dict) and bool(tag.get('blockHash'))
    def _reserve(self,k,method,params=None,immutable=False,block_fetch=False):
        self.raise_if_stopped()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            # Recheck under the SQLite write lock: another process may have filled the cache
            # between the initial lookup and this reservation. Never reserve/download it again.
            cached=None
            if immutable:
                if block_fetch:
                    if method=='eth_getBlockByNumber':cached=self.db.execute('SELECT v FROM blocks WHERE n=?',(int(params[0],16),)).fetchone()
                    else:cached=self.db.execute('SELECT v FROM blocks WHERE h=?',(params[0].lower(),)).fetchone()
                else:cached=self.db.execute('SELECT v FROM cache WHERE k=?',(k,)).fetchone()
            if cached:
                self.db.rollback();return ('cached',json.loads(cached[0]))
            used=self._used();cost=self.costs[method]
            if used>=self.max_cu or used+cost>self.max_cu:
                self.stopped=f'CU-GRENSE: {used} estimert CU reservert; neste {method} trenger {cost}; grense {self.max_cu}. Ingen nytt kall sendt.'
                raise QuotaStop(self.stopped)
            if self.invocation_requests>=self.max_requests:
                self.stopped='RPC-forsøksgrensen er nådd. Ingen nytt kall sendt.';raise QuotaStop(self.stopped)
            pending=self.db.execute("SELECT id FROM attempts WHERE status='pending' LIMIT 1").fetchone()
            if pending and not self.retry_uncertain:
                self.stopped='UKJENT LEVERING: tidligere forespørsel mangler lagret svar. Ingen automatisk reprise.'
                raise UncertainRequest('En tidligere forespørsel ble avbrutt før resultatet ble lagret. Levering er ukjent; ingen automatisk gjentakelse. Se KVOTE.md.')
            if pending:self.db.execute("UPDATE attempts SET status='unknown-retried' WHERE status='pending'")
            row=self.db.execute("INSERT INTO attempts(k,method,cu,status,at) VALUES (?,?,?,'pending',?)",(k,method,cost,time.time()))
            self.db.commit();self.invocation_requests+=1
            return row.lastrowid
        except BaseException:self.db.rollback();raise
    def _finish(self,attempt,status,cache_value=None,cache_key=None,block=None):
        with self.db:
            self.db.execute('UPDATE attempts SET status=? WHERE id=?',(status,attempt))
            if cache_key and cache_value is not None:
                self.db.execute('INSERT OR REPLACE INTO cache VALUES (?,?)',(cache_key,json.dumps(cache_value,separators=(',',':'))))
            if block:
                self.db.execute('INSERT OR REPLACE INTO blocks VALUES (?,?,?)',(int(block['number'],16),block['hash'].lower(),json.dumps(block,separators=(',',':'))))
        self.write_summary()
    def _transport(self,method,params):
        req=urllib.request.Request(self.url,data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode(),headers={'Content-Type':'application/json'})
        # No retries here: every subsequent attempt must reserve new CU first.
        with self.opener(req,timeout=60) as response:return json.load(response)
    def _fetch(self,method,params,immutable,block_fetch=False):
        k=self._key(method,params)
        if immutable:
            cached=self.db.execute('SELECT v FROM cache WHERE k=?',(k,)).fetchone()
            if cached:self.cache_hits+=1;return json.loads(cached[0])
        attempt=self._reserve(k,method,params,immutable,block_fetch)
        if isinstance(attempt,tuple):self.cache_hits+=1;return attempt[1]
        self.write_summary()
        try:
            response=self._transport(method,params)
        except urllib.error.HTTPError as error:
            self._finish(attempt,'failed')
            raise RPCError(f'{method}: HTTP {error.code}; endpoint og svar skjult. Forsøket er CU-reservert.') from None
        except (urllib.error.URLError,TimeoutError,OSError):
            # A timeout/disconnect does not prove whether upstream performed/billed the request.
            self.stopped='UKJENT LEVERING: transportfeil. CU beholdes reservert; ingen automatisk reprise.'
            self.write_summary()
            raise UncertainRequest(f'{method}: transportfeil, levering ukjent. CU beholdes reservert; ingen automatisk reprise.') from None
        except (ValueError,TypeError):
            self._finish(attempt,'failed');raise RPCError(f'{method}: ugyldig JSON-svar; detaljer skjult.') from None
        if not isinstance(response,dict) or 'error' in response or 'result' not in response:
            self._finish(attempt,'failed')
            error=response.get('error') if isinstance(response,dict) else None
            code=error.get('code') if isinstance(error,dict) else None
            if not isinstance(code,int):code=None
            raise RPCError(f'{method}: RPC-feil {code}; detaljer skjult. Forsøket er CU-reservert.')
        value=response['result']
        if block_fetch and value is not None:
            try:
                assert isinstance(value,dict) and isinstance(value['hash'],str) and value['hash'].startswith('0x')
                int(value['number'],16);assert all(isinstance(tx,dict) and 'hash' in tx for tx in value['transactions'])
                if method=='eth_getBlockByNumber':assert int(value['number'],16)==int(params[0],16)
                else:assert value['hash'].lower()==params[0].lower()
            except (AssertionError,KeyError,TypeError,ValueError):
                self._finish(attempt,'failed');raise RPCError('Ufullstendig/feil fullblokk. Ingen blokkcache skrevet.') from None
        # Do not permanently cache null receipts or missing blocks, which might be transient.
        self._finish(attempt,'success',value if immutable and not block_fetch else None,k if immutable and not block_fetch else None,value if block_fetch else None)
        return value
    def call(self,method,params):
        with self.lock:
            if method not in self.costs:raise RPCError('RPC-metoden er ikke i CU-tabellen. Blokkert uten videresending.')
            if method in ('eth_getBlockByNumber','eth_getBlockByHash'):
                if len(params)!=2 or not isinstance(params[1],bool):raise RPCError('Ugyldige blokkparametere')
                selector=params[0]
                if method=='eth_getBlockByNumber' and selector=='latest':selector=self.call('eth_blockNumber',[])
                if not isinstance(selector,str) or not selector.startswith('0x'):raise RPCError('Kun eksplisitt blokk eller latest støttes')
                if method=='eth_getBlockByNumber':
                    number=int(selector,16);row=self.db.execute('SELECT v FROM blocks WHERE n=?',(number,)).fetchone();selector=hex(number)
                else:row=self.db.execute('SELECT v FROM blocks WHERE h=?',(selector.lower(),)).fetchone()
                if row:self.cache_hits+=1;block=json.loads(row[0])
                else:block=self._fetch(method,[selector,True],True,True)
                if block is None:return None
                if params[1]:return block
                return {**block,'transactions':[tx['hash'] for tx in block['transactions']]}
            if method in ('eth_chainId','net_version') and method in self.session_metadata:
                self.cache_hits+=1;return self.session_metadata[method]
            if method=='eth_blockNumber' and self.head is not None:
                self.cache_hits+=1;return self.head
            value=self._fetch(method,params,self._immutable(method,params))
            if method=='eth_blockNumber':self.head=value
            if method in ('eth_chainId','net_version'):self.session_metadata[method]=value
            return value
    def close(self):
        self.write_summary();self.db.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

class GuardedRPC(RPC):
    def __init__(self,client):self.client=client;self.db=None
    @property
    def calls(self):return self.client.invocation_requests
    def call(self,method,params,cache=True):return self.client.call(method,params)

class QuotaGateway:
    """Anvil sees only this tokenized loopback URL, never the credential-bearing endpoint."""
    def __init__(self,client):self.client=client;self.server=None
    def __enter__(self):
        client=self.client;path='/'+secrets.token_urlsafe(24)
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                if self.path!=path:self.send_error(403);return
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=2_000_000:raise ValueError()
                    body=json.loads(self.rfile.read(size));batch=isinstance(body,list)
                    requests=body if batch else [body]
                    if not 1<=len(requests)<=128:raise ValueError()
                    responses=[]
                    for r in requests:
                        try:result=client.call(r['method'],r.get('params',[]));response={'jsonrpc':'2.0','id':r.get('id'),'result':result}
                        except (QuotaStop,UncertainRequest) as e:
                            # Do not send server details that Anvil might reproduce in its logs.
                            response={'jsonrpc':'2.0','id':r.get('id'),'error':{'code':-32098,'message':'Guard stopped: estimated quota or uncertain request'}}
                        except (RPCError,ValueError,TypeError,KeyError):response={'jsonrpc':'2.0','id':r.get('id'),'error':{'code':-32097,'message':'Guarded archive read failed; details redacted'}}
                        responses.append(response)
                    data=json.dumps(responses if batch else responses[0]).encode();self.send_response(200)
                    self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
                except (ConnectionAbortedError,ConnectionResetError,BrokenPipeError):
                    # Anvil may close a local request before reading its reply.
                    # The upstream reservation/cache is already retained: never retry here.
                    return
                except (ValueError,TypeError,KeyError):self.send_error(400)
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}{path}';return self
    def __exit__(self,*args):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=3)
