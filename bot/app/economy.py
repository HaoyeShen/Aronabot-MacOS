"""Opt-in local-only routing for a bounded allowlist of helper tasks."""
import json,logging,os,re,subprocess,threading,time,urllib.request
from pathlib import Path
from .model_client import make_client
from .model_audit import model_call
from .paths import LOGS
log=logging.getLogger(__name__)
PURPOSES={'上下文摘要','关键词是否对机器人说话','概率命中后：判断是否回复','群聊回复对象判断'}
URL='http://127.0.0.1:11434'

def local_models(*,start=False):
    def read():
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL+'/api/tags',timeout=1.5) as response:return [m['name'] for m in json.load(response).get('models',[])]
    try:return read()
    except OSError:
        if not start:raise
    executable=next((p for p in ('/usr/local/bin/ollama','/opt/homebrew/bin/ollama','/Applications/Ollama.app/Contents/Resources/ollama') if Path(p).is_file()),None)
    if not executable:raise RuntimeError('未安装 Ollama，本轮使用原模型')
    LOGS.mkdir(parents=True,exist_ok=True)
    with (LOGS/'economy-ollama.log').open('ab') as output:
        subprocess.Popen([executable,'serve'],stdin=subprocess.DEVNULL,stdout=output,stderr=output,
            env={**os.environ,'OLLAMA_HOST':'127.0.0.1:11434'},start_new_session=True)
    for _ in range(10):
        time.sleep(.1)
        try:return read()
        except OSError:pass
    raise RuntimeError('本地推理服务尚未就绪')

class EconomyRouter:
    def __init__(self,config):
        self.config=config;self.lock=threading.Lock();self.retry_after=0.;self.local_tasks=0;self.fallbacks=0;self.last='尚未调用'
        self.model_cache=None;self.checked_at=0.
    def try_chat(self,profile,messages,system,*,purpose):
        settings=self.config.bot
        if not settings.get('economy_enabled',False) or purpose not in PURPOSES or profile.get('provider') in ('ollama','mock'):return None
        if any(not isinstance(m.get('content',''),str) or m.get('images') for m in messages):return None
        size=len(system)+sum(len(m.get('content','')) for m in messages)
        if size>(9000 if purpose=='上下文摘要' else 5000):return None
        # UTF-8 bytes bound token count conservatively, leaving room for the
        # output and chat template; never silently truncate a summary input.
        if len((system+''.join(m.get('content','') for m in messages)).encode('utf-8'))>12000:return None
        if time.monotonic()<self.retry_after or not self.lock.acquire(False):return None
        try:
            model=settings.get('economy_local_model','qwen3.5:9b')
            if not isinstance(model,str) or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,100}',model):raise ValueError('本地模型名称无效')
            if self.model_cache is None or time.monotonic()-self.checked_at>60:
                self.model_cache=local_models(start=True);self.checked_at=time.monotonic()
            if model not in self.model_cache:raise RuntimeError('未安装所选本地模型')
            local={'provider':'ollama','base_url':URL,'model':model,'think':False,'temperature':0,
                   'max_tokens':700 if purpose=='上下文摘要' else 32,'timeout':10,'num_ctx':16384,
                   '_reasoning_intensity':'medium'}
            if purpose=='上下文摘要':
                system+='\n按发言者逐人保留事实、约定和状态。代词只能归属其发言者，某人取消参加不代表其他人取消约定；不得合并不同人的事实。只输出有依据的摘要。'
            result=model_call(make_client(local),'chat',purpose,messages,system)
            text=result.text.strip()
            allowed={'群聊回复对象判断':{'BOT','OTHER','ALL','UNKNOWN'},'关键词是否对机器人说话':{'YES','NO'},'概率命中后：判断是否回复':{'YES','NO'}}
            if purpose in allowed:
                if text.upper() not in allowed[purpose]:raise ValueError('本地分类输出格式无效')
            elif not 10<=len(text)<=2000 or '<think>' in text or '<tool' in text:raise ValueError('本地摘要输出无效')
            self.local_tasks+=1;self.last='本地完成：'+purpose
            log.info('节省模式 · 本地完成 · %s · %s',purpose,model)
            return result
        except Exception as exc:
            self.fallbacks+=1;self.last='本地不可用，使用原模型：'+type(exc).__name__
            self.retry_after=time.monotonic()+60;self.model_cache=None
            log.warning('节省模式 · %s · 本地失败，回退原模型 · %s',purpose,type(exc).__name__)
            return None
        finally:self.lock.release()
