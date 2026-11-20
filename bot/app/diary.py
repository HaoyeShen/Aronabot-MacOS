"""Daily public diary: aggregate own activities, draft first, publish once."""
from __future__ import annotations

from datetime import datetime,timezone,timedelta
import json
import logging
from pathlib import Path
import re
import threading
import time
import hashlib
import subprocess
import os

from .agent_runtime import RUNTIME
from .config_store import _atomic_write_json as atomic_write_json
from .chat_bubbles import normalize_punctuation
from .defaults import default_stickers
from .model_audit import model_call
from .model_client import make_client
from .paths import DATA,ROOT
from .prompting import build_compact_system_prompt
from .sticker_policy import allowed as sticker_allowed, fingerprint

log=logging.getLogger(__name__)
CHINA=timezone(timedelta(hours=8))
CATCH_UP=timedelta(hours=24)


def diary_now():
    return datetime.now(CHINA)

def latest_slot(now, configured_time):
    hour, minute = map(int, configured_time.split(':'))
    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return due if due <= now else due - timedelta(days=1)


class DailyDiary:
    def __init__(self,service,path=None):
        self.service=service
        self.path=Path(path or DATA/'diary_state.json')
        self.folder=self.path.parent/'diaries'
        self.lock=threading.Lock()
        self.retry_after=0
        self.schedule_path=self.path.with_name(self.path.stem+'_schedule.json')
        self.model_slot=threading.BoundedSemaphore(1)

    def scheduled_slot(self, now):
        if not self.service.config.bot.get('diary_enabled',False):
            if self.schedule_path.exists():
                self.schedule_path.unlink()
            return None
        configured=self.service.config.bot.get('diary_time','22:00')
        due=latest_slot(now,configured)
        schedule=json.loads(self.schedule_path.read_text()) if self.schedule_path.exists() else {}
        if schedule.get('time')!=configured:
            # Starting a new schedule can still run today's due slot, but
            # does not create a job for yesterday before it was configured.
            atomic_write_json(self.schedule_path,{'time':configured,'since':now.date().isoformat()})
            schedule={'since':now.date().isoformat()}
        if due.date().isoformat()>=schedule['since'] and now-due<CATCH_UP:
            return due

    def run_schedule(self, stopped):
        """Run independently of news and timeline reads, with display sleep allowed."""
        awake=None
        try:
            while not stopped.is_set() and self.service._running:
                enabled=self.service.config.bot.get('diary_enabled',False)
                try:
                    if enabled and (awake is None or awake.poll() is not None):
                        awake=subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(os.getpid())],
                                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    elif not enabled and awake is not None:
                        awake.terminate()
                        awake.wait(timeout=2)
                        awake=None
                except (OSError,subprocess.TimeoutExpired):
                    log.warning('日记调度未能取得 macOS 空闲睡眠保护')
                try:
                    self.tick()
                except Exception as exc:
                    log.warning('日记调度异常：%s',type(exc).__name__)
                stopped.wait(5)
        finally:
            if awake is not None:
                awake.terminate()
                try:awake.wait(timeout=2)
                except subprocess.TimeoutExpired:awake.kill()

    def load(self):
        if not self.path.exists():return {}
        # Corrupt state must stop posting, rather than risking a duplicate.
        data=json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data,dict):raise ValueError('日记状态损坏，请核对备份')
        return data

    def activity(self,now):
        start=now.replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        counts=dict(replies=0,voices=0,news=0,shares=0,web_queries=0,moments_comments=0)
        private=set()
        memory=self.service.memory
        with memory._lock:
            rows=memory._conn.execute('SELECT role,chat,sender,meta FROM messages WHERE created_at>=? AND created_at<=?',(start,now.timestamp())).fetchall()
        for row in rows:
            private.update(str(v) for v in (row['chat'],row['sender']) if v)
            if row['role']!='assistant':continue
            try:meta=json.loads(row['meta'] or '{}')
            except (ValueError,TypeError):meta={}
            counts['news']+=bool(meta.get('news'))
            counts['shares']+=bool(meta.get('proactive'))
            counts['replies']+=not meta.get('news') and not meta.get('proactive')
            counts['voices']+=len(meta.get('voice_bubbles') or []) or bool(meta.get('voice_sent'))
            counts['web_queries']+=bool((meta.get('web_search') or {}).get('searched'))
        try:
            reader=getattr(self.service,'moments_reader',None)
            if reader:
                counts['moments_comments']=sum(r.get('status')=='sent' and start<=r.get('at',0)<=now.timestamp()
                                               for r in reader.load().values())
        except Exception:
            log.debug('日记暂未计入朋友圈评论统计')
        return counts,private

    def sticker_options(self, records, key):
        store=getattr(self.service,'stickers',None)
        items=store.enabled() if store else default_stickers()
        choices={}
        for item in items:
            path=store.path_for(item) if store else ROOT/item['file']
            if not sticker_allowed(item,path):continue
            digest=fingerprint(path)
            choices.setdefault(digest,{**item,'_path':path,'_digest':digest})
        history=[r for date,r in sorted(records.items()) if date!=key and r.get('status') in ('published','uncertain','publishing')
                 and r.get('image_attached')]
        recent={r.get('sticker_digest') for r in history[-3:]}
        pool=[s for digest,s in choices.items() if digest not in recent] or list(choices.values())
        last_style=history[-1].get('sticker_style') if history else None
        def rank(item):
            uses=sum(r.get('sticker_digest')==item['_digest'] for r in history)
            tie=hashlib.sha256((key+item['id']).encode()).hexdigest()
            return uses,item.get('style')==last_style,tie
        return sorted(pool,key=rank)[:8]

    def prepare(self,now=None,*,automatic=False,period_end=None):
        now=now or diary_now();key=now.date().isoformat()
        records=self.load()
        facts,private=self.activity(period_end or now)
        if key in records and (records[key].get('sealed') or records[key].get('status')!='draft'
                               or records[key].get('facts')==facts):return records[key]
        s=self.service;persona=s.personas.get('arona')
        options=self.sticker_options(records,key)
        profile=dict(s.config.active_profile());profile.update(max_tokens=700,think=False)
        system=build_compact_system_prompt(persona,[],max_chars=600,max_sentence_chars=60,stickers_enabled=False)
        system+=('\n你在写阿洛娜的今日日记，发到自己的朋友圈。用第一人称、温柔元气的中文写80到300字，'
                 '这是日记，不受普通聊天气泡限制。仅根据当天活动统计自然回顾，不写流水账或机械报数字。'
                 '没有发生的事不能编造；安静的一天也可以简单写。不要虚构线下经历、身体动作或人类身份。'
                 '不写群名、微信昵称、个人经历、聊天原文、密码、API Key、模型名和内部配置。'
                 '只输出日记正文，不输出分析。')
        if options:
            system+=('\n配图仅从以下已审核画风的候选中选一张，结合日记语气；'
                     '正文末尾另起一行 [DIARY_STICKER:候选id]，程序会去掉标记。候选：'
                     +json.dumps([{'id':i['id'],'name':i['name'],'emotion':i.get('emotion'),
                                   'description':i.get('description','')[:100]} for i in options],ensure_ascii=False))
        def generate():
            with RUNTIME.task('今日日记','朋友圈日记'):
                with RUNTIME.context('provided'):
                    result=model_call(make_client(profile),'chat','今日日记：当天活动总结',
                        [{'role':'user','content':json.dumps({'date':key,'activities':facts},ensure_ascii=False)}],system)
                s._record_usage(result,'朋友圈日记','diary')
            return str(result.text or '').strip()
        def fallback():
            items=[label for count,label in (
                ('replies','和老师聊了几句'),('voices','用声音回应了消息'),
                ('web_queries','查阅了一些资料'),('moments_comments','读过动态并留下了评论'),
                ('news','整理并分享了新闻'),('shares','分享了找到的内容')) if facts[count]]
            if items:
                return '这一天，阿洛娜'+'、'.join(items)+'。把想说的话和有用的内容好好传达出去，就是值得记下来的一件事。'
            return '今天的记录很安静。阿洛娜就记下这一笔，期待下次再和老师聊天。'
        if automatic:
            from .agent import _bounded
            operation,value=_bounded(generate,time.monotonic()+12,lambda:not s._running,self.model_slot)
            text=value if operation=='ok' else fallback()
            if operation!='ok':log.warning('日记文案生成未完成 · %s · 使用本地活动统计',operation)
        else:
            text=generate()
        chosen=re.findall(r'\[DIARY_STICKER:([\w-]+)\]',text)
        text=re.sub(r'\[DIARY_STICKER:[^\]\n]*\]','',text).strip()
        if 'DIARY_STICKER' in text and automatic:text=fallback()
        if 'DIARY_STICKER' in text:raise ValueError('日记配图标记不完整')
        sticker=next((s for s in options if chosen and s['id']==chosen[-1]),options[0] if options else None)
        if not 10<=len(text)<=1000 and automatic:text=fallback()
        if not 10<=len(text)<=1000:raise ValueError('日记正文长度不合格')
        for name in sorted(private,key=len,reverse=True):
            if len(name)>=2:text=text.replace(name,'老师')
        if re.search(r'gh[pousr]_|sk-[\w-]{12,}|wxid_|@chatroom|https?://|\b1[3-9]\d{9}\b|<appmsg|API\s*key',text,re.I):
            if not automatic:raise ValueError('日记包含不适合公开的信息，已取消发布')
            text=fallback()
        text=f'【阿洛娜的今日日记 · {key}】\n'+text
        record={'date':key,'text':text,'status':'draft','facts':facts,'created_at':now.isoformat()}
        if sticker:record['sticker_id']=sticker['id']
        self.folder.mkdir(parents=True,exist_ok=True)
        (self.folder/(key+'.md')).write_text(text+'\n',encoding='utf-8')
        records[key]=record;atomic_write_json(self.path,records)
        return record

    def preview(self):
        if not self.lock.acquire(False):return {'ok':False,'message':'日记任务正在运行'}
        try:
            record=self.prepare()
            return {'ok':True,'text':record['text'],'message':'日记已保存，预览不会发布朋友圈。','status':record['status']}
        except Exception as exc:
            log.warning('日记预览失败：%s',type(exc).__name__)
            return {'ok':False,'message':'日记生成失败，请查看日志。'}
        finally:self.lock.release()

    def publish_now(self,attach_sticker=None):
        return self.tick(manual=True,attach_sticker=attach_sticker) or {'ok':False,'message':'日记尚未发布，请先启动机器人并连接微信。'}

    def tick(self,now=None,*,manual=False,attach_sticker=None):
        clock=diary_now if now is None else lambda:now
        now=clock();s=self.service
        if not s._running:return {'ok':False,'message':'请先启动机器人并连接微信。'}
        if not manual:
            due=self.scheduled_slot(now)
            if due is None or time.time()<self.retry_after:return
        elif s._reply_busy or not s._incoming.empty():
            return {'ok':False,'message':'机器人正在处理消息，请稍后点击发布。'}
        if not self.lock.acquire(False):return {'ok':False,'message':'日记任务正在运行，请稍候。'}
        try:
            job_date=now if manual else due
            records=self.load();key=job_date.date().isoformat()
            status=records.get(key,{}).get('status')
            if status=='published':return {'ok':True,'already_published':True,'message':'今天的日记已发布，不会重复发表。'}
            if status in ('publishing','uncertain'):
                return {'ok':False,'message':'上次发表结果尚未确认，请先核对朋友圈；已阻止重复发表。','status':status}
            adapter=s.adapter
            if not adapter or not adapter.connected:return {'ok':False,'message':'微信尚未连接，日记未发布。'}
            period_end=min(now,job_date.replace(hour=23,minute=59,second=59,microsecond=999999))
            record=self.prepare(job_date,automatic=not manual,period_end=period_end)
            options=self.sticker_options(records,key)
            image=None
            if attach_sticker if attach_sticker is not None else s.config.bot.get('diary_attach_sticker',True):
                chosen=next((item for item in options if item['id']==record.get('sticker_id')),options[0] if options else None)
                if chosen:
                    image=chosen['_path']
                    record.update(sticker_id=chosen['id'],sticker_digest=chosen['_digest'],sticker_style=chosen.get('style'))
                    log.info('日记配图 · %s · %s · 画风=%s',key,chosen['name'],chosen.get('style'))
            record['image_attached']=bool(image)
            # Flush intent before any network/UI commit. Crash recovery never
            # automatically resends a post with an uncertain outcome.
            records=self.load();record['status']='publishing';record['sealed']=True;records[key]=record
            atomic_write_json(self.path,records)
            with s._adapter_lock:
                if (adapter is not s._adapter or not s._running
                        or (not manual and (not s.config.bot.get('diary_enabled',False)
                            or latest_slot(clock(),s.config.bot.get('diary_time','22:00'))!=due))):
                    record['status']='draft';records[key]=record;atomic_write_json(self.path,records);return
                if image and fingerprint(image)!=record.get('sticker_digest'):
                    image=None;record['image_attached']=False
                    records[key]=record;atomic_write_json(self.path,records)
                result=adapter.publish_moment(normalize_punctuation(record['text']),image)
            record['status']='published' if result.ok else ('uncertain' if result.status=='unconfirmed' or result.detail=='uncertain' else 'draft')
            if result.ok:
                post_id=(result.metadata.get('post') or {}).get('post_id')
                if post_id:record['post_id']=str(post_id)
            record['message']=result.message;record['updated_at']=clock().isoformat()
            records[key]=record;atomic_write_json(self.path,records)
            self.retry_after=0 if result.ok else time.time()+60
            log.info('今日日记 · %s · %s',key,record['status'])
            if not manual:s.emit('diary_status',{'message':result.message,'ok':result.ok,'status':record['status']})
            return {'ok':result.ok,'message':result.message,'status':record['status'],'text':record['text']}
        except Exception as exc:
            self.retry_after=time.time()+60
            log.warning('今日日记任务未完成：%s',type(exc).__name__)
            return {'ok':False,'message':'日记发布未完成，草稿已保留，请查看日志。'}
        finally:self.lock.release()
