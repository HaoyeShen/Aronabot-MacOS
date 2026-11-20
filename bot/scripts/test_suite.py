"""Run every ported upstream suite in an isolated data directory, without live WeChat."""
from __future__ import annotations
import concurrent.futures,json,os,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def worker(test):
    with tempfile.TemporaryDirectory(prefix='wemac-test-') as temp:
        env=dict(os.environ,ARONA_DATA_DIR=temp,PYTHONPATH=os.pathsep.join((str(ROOT),str(ROOT.parent/'src'))))
        script="""import runpy,sys,socket,ipaddress
# Fixtures use public URLs without requiring DNS/network access in offline tests.
resolver=socket.getaddrinfo
def fixture_dns(host,port,*args,**kwargs):
    try:ipaddress.ip_address(host);return resolver(host,port,*args,**kwargs)
    except ValueError:pass
    if host=='localhost':return resolver(host,port,*args,**kwargs)
    return [(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('93.184.216.34',port))]
socket.getaddrinfo=fixture_dns
# Offline suites must never wait on a real outbound socket.  A test that
# forgets to stub a network call now fails immediately instead of hanging
# until the 120s watchdog (seen with a duplicate-reply repair call).
real_connect=socket.create_connection
def offline_connect(address,*args,**kwargs):
    host=address[0] if isinstance(address,tuple) else str(address)
    if host in ('127.0.0.1','::1','localhost'):return real_connect(address,*args,**kwargs)
    raise ConnectionRefusedError('outbound network disabled in offline tests: %s' % (host,))
socket.create_connection=offline_connect
from app import secretstore
class MemoryKeys:
    values={}
    def set_password(self,service,name,value):self.values[service,name]=value
    def get_password(self,service,name):return self.values.get((service,name))
keys=MemoryKeys()
secretstore._backend=lambda:keys
sys.argv=[sys.argv[1]]
runpy.run_path(sys.argv[0],run_name='__main__')
"""
        start=time.monotonic()
        try:
            r=subprocess.run([sys.executable,'-u','-c',script,str(test)],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=120)
            result={'name':test.name,'ok':r.returncode==0,'seconds':round(time.monotonic()-start,2),'output':r.stdout}
        except subprocess.TimeoutExpired as exc:result={'name':test.name,'ok':False,'seconds':120,'output':'TIMEOUT\n'+str(exc.stdout)}
        print(('PASS ' if result['ok'] else 'FAIL ')+test.name,flush=True)
        if not result['ok']:print(result['output'][-4500:],flush=True)
        return result

if __name__=='__main__':
    tests=sorted((ROOT/'tests').glob('*_test.py'))
    if len(sys.argv)>1:tests=[p for p in tests if any(v in p.name for v in sys.argv[1:])]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(worker,tests))
    report=ROOT/'.runtime/test-report.json';report.parent.mkdir(exist_ok=True)
    report.write_text(json.dumps(results,ensure_ascii=False,indent=2))
    print(f'{sum(r["ok"] for r in results)}/{len(results)} suites passed; report: {report}')
    raise SystemExit(any(not r['ok'] for r in results))
