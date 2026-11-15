"""macOS WeChat transport, exclusively through Wemac-auto internal functions."""
from __future__ import annotations
import hashlib,importlib.util,json,logging,re,threading,time
from dataclasses import dataclass,field
from pathlib import Path
from typing import Callable
from .paths import DATA,DEFAULT_NATIVE_PROFILE
from .reply_control import fresh_send,reply_current

log=logging.getLogger(__name__)

@dataclass
class IncomingMessage:
    chat:str
    sender:str
    content:str
    msg_type:str='text'
    external_id:str=''
    attr:str='friend'
    chat_type:str='friend'
    direction:str='in'
    origin:str='friend'
    image_path:str=''
    raw:object|None=None
    received_at:float=field(default_factory=time.time)
    mentions_self:bool=False
    @property
    def is_self(self):return self.direction=='out' or self.attr in ('self','system')
    @property
    def is_group(self):return self.chat_type=='group'

@dataclass
class HistoryMessage:
    chat:str
    sender:str
    content:str
    role:str
    msg_type:str='text'
    external_id:str=''
    attr:str='friend'
    direction:str='in'
    origin:str='friend'
    received_at:float=field(default_factory=time.time)

@dataclass
class SendResult:
    ok:bool
    message:str=''
    detail:str=''
    status:str=''
    server_message_id:str=''
    metadata:dict=field(default_factory=dict)
    def __bool__(self):return self.ok


def detect_wechat_backends():
    return {'native':importlib.util.find_spec('frida') is not None and importlib.util.find_spec('wechat_aumac') is not None}


class BaseWeChatAdapter:
    name='base'
    def __init__(self,config,on_message,on_status=None):
        self.config=config;self.on_message=on_message;self.on_status=on_status or (lambda *a:None)
        self._targets={};self._running=False;self._last_message_at=0.;self.connected=False
        self.self_name='';self.self_wxid='';self.backend_label=self.name
        self._recent_sent={};self._sent_lock=threading.Lock();self._transport_lock=threading.RLock()
    @staticmethod
    def _normalise_sent(text):return ' '.join(str(text or '').split()).strip()
    def _remember_sent(self,chat,text,*,kind='text'):
        value=self._normalise_sent(text)
        if not value:return
        with self._sent_lock:
            items=self._recent_sent.setdefault(chat,[]);items.append((time.time(),value))
            self._recent_sent[chat]=[(stamp,t) for stamp,t in items if time.time()-stamp<180][-20:]
    def _is_recent_sent(self,chat,text,window=90):
        with self._sent_lock:return any(time.time()-stamp<=window and self._normalise_sent(text)==t for stamp,t in self._recent_sent.get(chat,[]))
    def start(self,targets):raise NotImplementedError
    def stop(self):self._running=False;self.connected=False
    @fresh_send
    def send_text(self,chat,text):raise NotImplementedError
    @fresh_send
    def send_quoted_text(self,chat,text,quote_text='',quote_kind='text',reference=None):return self.send_text(chat,text)
    @fresh_send
    def send_sticker(self,chat,path):raise NotImplementedError
    def fetch_recent(self,chat,limit):raise NotImplementedError
    def unread_sessions(self,limit=200):return []
    def probe(self):return False,'适配器尚未连接'
    def canonical_chat(self,chat):return str(chat or '').strip()
    def chat_identity(self,chat):return self.canonical_chat(chat)
    def resolve_action_target(self,chat):return None
    def is_same_chat(self,current,expected):return bool(current and expected and self.chat_identity(current)==self.chat_identity(expected))
    def validate_group_chat(self,chat):return SendResult(True)
    def finalize_voice_send(self,chat):return SendResult(True)
    def read_moments(self,limit=30):return []
    def publish_moment(self,text,image_path=None,*,dry_run=False):return SendResult(False,'此适配器没有朋友圈发布接口。')
    def comment_moment(self,post,text,*,dry_run=False,allowed=lambda:True):return SendResult(False,'此适配器没有朋友圈评论接口。')
    def status(self):return dict(connected=self.connected,backend=self.backend_label,self_name=self.self_name,last_message_at=self._last_message_at)


class NativeWeChatAdapter(BaseWeChatAdapter):
    name='native'
    requires_message_reference=True
    model_delivery=True
    def __init__(self,config,on_message,on_status=None):
        super().__init__(config,on_message,on_status)
        self._session=None;self._thread=None;self._stop=threading.Event();self._by_id={};self._aliases={}
        self._unread={};self._native_stickers=None;self._sent_ids=set();self._inflight={};self._bindings={}
        self.backend_label='macOS · 内部函数 · 后台收发'
    def _settings(self):return self.config.get('wechat',self.config)
    @staticmethod
    def _internal(value):return bool(re.fullmatch(r'[A-Za-z0-9_.@-]{1,128}',str(value or '')) )
    def _resolve_username(self,chat):
        value=str(chat or '').strip()
        if value in self._aliases:return self._aliases[value]
        if value=='filehelper':return value
        if self._internal(value) and (value.startswith('wxid_') or value.endswith('@chatroom')):
            return value
        matches={str(t.get('internal_id') or t.get('wxid') or '') for t in self.config.get('targets',[]) if value in [t.get('name'),t.get('nickname'),t.get('remark')]}
        matches.discard('')
        if len(matches)==1:return matches.pop()
        if self._session and hasattr(self._session,'resolve_contact'):
            record=self._session.resolve_contact(value)
            if record:return record['user_id']
        return None
    def start(self,targets):
        from wechat_aumac.native import NativeSession
        self._stop.clear();settings=self._settings();profile=Path(settings.get('native_profile') or DEFAULT_NATIVE_PROFILE).expanduser().resolve()
        if not profile.is_file():raise RuntimeError('请在设置中选择本机微信原生 profile。')
        catalog=json.loads(profile.read_text())
        reads=tuple(k for k in ('moment_timeline','moment_detail') if k in catalog.get('readSubmits',{}))
        moments=tuple(a for a,k in [('publish','moment_post'),('like','moment_interaction'),('comment','moment_interaction'),('unlike','moment_objectop')] if k in catalog.get('momentSubmits',{}))
        actions=tuple(a for a,k in [('quote','app_message'),('revoke','revoke')] if k in catalog.get('messageSubmits',{}))
        wx=NativeSession(profile,mode='full',read_operations=reads,moments_operations=moments,message_operations=actions,pid=settings.get('pid') or None)
        try:
            wx.connect();self._session=wx;identity=wx.identity();self.self_wxid=identity['user_id']
            try:nickname=wx.get_display_name(self.self_wxid)
            except Exception:nickname=''
            self.self_name=str(settings.get('self_name') or nickname or '阿洛娜')
            self.config['targets']=list(targets)
            self._targets={t['name']:dict(t) for t in targets};self._by_id={};self._aliases={}
            for target in targets:
                user=str(target.get('internal_id') or target.get('wxid') or self._resolve_username(target['name']) or '')
                if not self._internal(user):raise ValueError(f'无法唯一确定「{target["name"]}」的内部 ID；请在测试对象中填写准确 wxid／群 ID。')
                self._aliases[target['name']]=user
                if user not in self._by_id:self._by_id[user]=target
                self._aliases[user]=user
            self.private_admin_identities={}
            for admin in settings.get('private_admins',[]):
                if admin=='__self__':continue
                record=wx.resolve_contact(admin)
                if not record or record.get('type')!='friend':continue
                user=record['user_id'];self.private_admin_identities[admin]=user
                self._aliases[admin]=user;self._aliases[user]=user
                self._by_id.setdefault(user,{'name':admin,'type':'friend','enabled':True})
            if not self._by_id:raise ValueError('请先添加并启用监听对象。')
            self.connected=True;self._running=True
            self._thread=threading.Thread(target=self._listen,name='wemac-native-listener',daemon=True);self._thread.start()
            self.on_status('connected',f'已连接独立微信账号，后台监听 {len(self._by_id)} 个会话。')
        except Exception:
            wx.close();self._session=None;self.connected=False;raise
    def reconfigure_targets(self,targets):
        """Resolve a complete replacement before swapping, without reattaching."""
        if not self.connected or not self._session:raise RuntimeError('原生会话未连接')
        aliases={};by_id={};items={}
        for target in targets:
            user=str(target.get('internal_id') or target.get('wxid') or '')
            if not user:
                contact=self._session.resolve_contact(target['name'])
                user=(contact or {}).get('user_id','')
            if not self._internal(user):raise ValueError('监听对象缺少唯一内部 ID')
            aliases[target['name']]=user;aliases[user]=user
            by_id.setdefault(user,dict(target));items[target['name']]=dict(target)
        for admin,user in getattr(self,'private_admin_identities',{}).items():
            aliases[admin]=user;aliases[user]=user
            by_id.setdefault(user,{'name':admin,'type':'friend','enabled':True})
        if not by_id:raise ValueError('请保留至少一个监听对象')
        with self._transport_lock:
            self.config['targets']=list(targets)
            self._targets=items;self._aliases=aliases;self._by_id=by_id

    def _listen(self):
        try:
            while not self._stop.is_set():
                event=self._session.next_event(timeout=.25)
                if self._session._detached:raise RuntimeError('微信已退出或重启，监听已停止。')
                if not event:continue
                if event.get('event') in ('probe_error','decode_error'):log.warning('原生消息解码：%s',event.get('detail'));continue
                if event.get('event') not in ('incoming_message','outgoing_message'):continue
                raw=event['message'];user=raw.get('chat_id','');target=self._by_id.get(user)
                if not target:
                    if raw.get('direction')=='incoming':self._unread[user]=self._unread.get(user,0)+1
                    continue
                message=self._map_message(raw,target)
                self._last_message_at=time.time();self.on_message(message)
        except Exception as exc:
            if not self._stop.is_set():log.exception('原生监听停止');self.on_status('error',str(exc))
        finally:self.connected=False;self._running=False
    def _map_message(self,raw,target):
        raw={**raw,'sender_username':raw.get('sender',''),'username':raw.get('chat_id','')}
        kind={1:'text',3:'image',34:'voice',43:'video',47:'emotion',49:'link'}.get(raw.get('message_type'),'text')
        outgoing=raw.get('direction')=='outgoing';system=raw.get('message_type',0)>=10000
        origin=('system' if system else 'bot_echo' if outgoing and (raw.get('origin')=='sdk' or raw.get('message_id') in self._sent_ids or self._inflight.get(raw.get('chat_id'))) else 'self' if outgoing else 'friend')
        content=raw.get('text','');path=''
        if kind=='link' and raw.get('card',{}).get('subtype')=='57':
            content=raw['card'].get('title') or content;kind='text'
        if kind in ('image','emotion') and hasattr(self._session,'download_media'):
            try:path=str(self._session.download_media(raw,DATA/'images/incoming'))
            except Exception:log.exception('原生媒体暂不可读取')
        mentioned=False
        try:
            from wechat_aumac.native.cards import parse_xml
            xml=parse_xml(raw.get('source_xml') or '<msgsource/>')
            names=xml.findtext('atuserlist') or ''
            mentioned=self.self_wxid in [v.strip() for v in names.split(',')] or 'notify@all' in names
        except Exception:pass
        sender=raw.get('sender_name') or ''
        if not sender and self._session:
            try:sender=self._session.get_display_name(raw.get('sender',''),chat_id=raw.get('chat_id'))
            except Exception:log.warning('发送者昵称暂不可读取，使用通用称呼。')
        if not isinstance(sender,str) or not sender or sender.startswith('wxid_'):
            sender='群友' if raw.get('chat_id','').endswith('@chatroom') else '对方'
        return IncomingMessage(target['name'],sender,content,
            kind,f'wxnative:{raw.get("chat_id")}:{raw.get("message_id")}',
            'system' if system else 'self' if outgoing else 'friend',
            'group' if raw.get('chat_id','').endswith('@chatroom') else 'friend',
            'system' if system else 'out' if outgoing else 'in',origin,path,raw,
            float(raw.get('timestamp') or time.time()),mentioned)
    def canonical_chat(self,chat):
        user=self._resolve_username(chat)
        return self._by_id[user]['name'] if user in self._by_id else str(chat or '').strip()
    def chat_identity(self,chat):return self._resolve_username(chat) or ''
    def resolve_action_target(self,chat):
        user=self._resolve_username(chat)
        if not user:return None
        target=self._by_id.get(user)
        if target:return {'name':target['name'],'username':user,'id':user,'nickname':target['name'],'remark':target['name'],'type':target.get('type','friend'),'identity':user,'chat':target['name']}
        if self._session and hasattr(self._session,'get_contact'):
            record=self._session.get_contact(user)
            return {**record,'identity':user,'chat':str(chat)} if record else None
        return None
    def validate_group_chat(self,chat):return SendResult(bool((self._resolve_username(chat) or '').endswith('@chatroom')),'目标必须是精确的原生群 ID。')
    def _destination(self,chat):
        if not self.connected or not self._session:raise RuntimeError('原生微信尚未连接。')
        user=self._resolve_username(chat)
        if not user:raise ValueError('无法唯一识别目标聊天，已取消发送。')
        return user
    def _result(self,result,text=''):
        status=result.get('status','unconfirmed');server=str(result.get('server_message_id') or '')
        if server:self._sent_ids.add(server)
        if len(self._sent_ids)>2000:self._sent_ids.clear()
        return SendResult(status=='acknowledged','服务器已确认' if status=='acknowledged' else '发送未确认，请勿自动重发。' if status=='unconfirmed' else '服务器拒绝发送。',result.get('detail',''),status,server,result)
    @fresh_send
    def send_text(self,chat,text):
        from .tool_protocol import internal_output
        if internal_output(text):return SendResult(False,'拦截内部工具协议，未发送。',status='rejected')
        user=self._destination(chat)
        with self._transport_lock:
            self._inflight[user]=True
            try:result=self._result(self._session.send_text(user,text));self._remember_sent(chat,text);return result
            finally:self._inflight.pop(user,None)
    @fresh_send
    def send_quoted_text(self,chat,text,quote_text='',quote_kind='text',reference=None):
        from .tool_protocol import internal_output
        if internal_output(text):return SendResult(False,'拦截内部工具协议，未发送。',status='rejected')
        user=self._destination(chat)
        if not isinstance(reference,dict):return SendResult(False,'引用缺少准确的原生消息对象。',status='rejected')
        with self._transport_lock:
            self._inflight[user]=True
            try:result=self._result(self._session.send_quote(user,text,reference));self._remember_sent(chat,text);return result
            finally:self._inflight.pop(user,None)
    @fresh_send
    def send_sticker(self,chat,path):
        from PIL import Image
        path=Path(path).expanduser().resolve();user=self._destination(chat)
        with Image.open(path) as image:fmt=image.format
        with self._transport_lock:
            result=self._session.send_sticker(user,path,cancelled=lambda:self._stop.is_set() or not reply_current()) if fmt=='GIF' else self._session.send_image(user,self._image_file(path,fmt))
            return self._result(result)
    @fresh_send
    def send_image(self,chat,path):
        from PIL import Image
        path=Path(path).expanduser().resolve()
        with Image.open(path) as image:fmt=image.format
        with self._transport_lock:
            return self._result(self._session.send_image(self._destination(chat),self._image_file(path,fmt)))
    def _image_file(self,path,fmt):
        if fmt in ('PNG','JPEG'):return path
        from PIL import Image
        folder=DATA/'temp/native-images';folder.mkdir(parents=True,exist_ok=True)
        dest=folder/(hashlib.sha256(path.read_bytes()).hexdigest()+'.png')
        with Image.open(path) as image:image.convert('RGBA').save(dest)
        return dest
    @fresh_send
    def send_voice(self,chat,path):
        with self._transport_lock:return self._result(self._session.send_voice(self._destination(chat),path,timeout=40))
    def fetch_recent(self,chat,limit):
        user=self._destination(chat)
        rows=(self._session.get_history(user,limit=limit) if hasattr(self._session,'get_history') else self._session.read(user,limit=limit))
        return [HistoryMessage(self.canonical_chat(chat),r.get('sender_name') or self._session.get_display_name(r.get('sender',''),chat_id=user) or '群友',r.get('text',''),
                'assistant' if r.get('direction')=='outgoing' else 'user',
                {3:'image',34:'voice',43:'video',47:'emotion',49:'link'}.get(r.get('message_type'),'text'),
                f'wxnative:{user}:{r["message_id"]}',direction='out' if r.get('direction')=='outgoing' else 'in',received_at=float(r.get('timestamp') or time.time())) for r in rows]
    def unread_sessions(self,limit=200):
        if not self._session:return []
        rows=self._session.get_sessions(limit=limit)
        return [{'name':self.canonical_chat(r['user_id']),'username':r['user_id'],'unread':r['unread']} for r in rows if r['unread']>0]
    def native_stickers(self):
        if self._native_stickers is None:
            from .native_stickers import NativeStickers
            self._native_stickers=NativeStickers(self._session)
        return self._native_stickers
    @fresh_send
    def send_native_sticker(self,chat,entry,*,allowed=lambda:True):
        if not allowed():return SendResult(False,'任务已取消',status='cancelled')
        path,_,_=self.native_stickers().preview(entry['id'])
        if not allowed() or not reply_current():return SendResult(False,'任务已取消',status='cancelled')
        return self.send_sticker(chat,Path(path))
    def read_moments(self,limit=30):
        posts=[];max_id=0
        while len(posts)<limit:
            response=self._session.get_moments(max_id=max_id)
            if response.get('status')!='acknowledged':raise RuntimeError('朋友圈读取未获服务器确认。')
            rows=response.get('posts',[])
            if not rows:break
            posts.extend({'id':r['post_id'],'tid':r['post_id'],'username':r['owner_id'],'nickname':r.get('nickname',''),
                          'text':r.get('text') or '','create_time':r.get('timestamp'),
                          'comments':[{**c,'username':c['user_id'],'content':c.get('text','')} for c in r.get('comments',[])],'native':r} for r in rows)
            next_id=min(int(r['post_id']) for r in rows)
            if next_id==max_id:break
            max_id=next_id
        return posts[:limit]
    def comment_moment(self,post,text,*,dry_run=False,allowed=lambda:True):
        if not allowed():return SendResult(False,'任务已取消',status='cancelled')
        current=self._session.get_moment(post['id'])
        native=current.get('post') or {}
        if current.get('status')!='acknowledged' or native.get('owner_id')!=post.get('username') or native.get('text')!=post.get('text'):
            return SendResult(False,'朋友圈作者、正文或 ID 已变化，未提交。',status='rejected')
        if dry_run:return SendResult(True,'原生目标核对通过，未提交评论。',status='preview')
        if not allowed():return SendResult(False,'任务已取消',status='cancelled')
        return self._result(self._session.comment_moment(post['id'],text))
    def publish_moment(self,text,image_path=None,*,dry_run=False):
        if dry_run:
            draft=self._session.prepare_moment(text,visibility='public');return SendResult(True,'已生成原生草稿，未发布。',status='preview',metadata={k:v for k,v in draft.items() if k!='payload'})
        if image_path and not hasattr(self._session,'publish_image_moment'):
            return SendResult(False,'朋友圈配图上传接口尚未接入，日记草稿已保留。',status='unsupported')
        result=(self._session.publish_image_moment(text,image_path,visibility='public') if image_path else
                self._session.publish_moment(text,visibility='public'))
        return self._result(result)
    def probe(self):
        if not self.connected or not self._session:return False,'原生通道未连接'
        try:self._session.status();return True,'内部函数通道在线，后台收发可用'
        except Exception as exc:return False,str(exc)
    def stop(self):
        self._stop.set();self._running=False
        thread=self._thread
        if thread and thread is not threading.current_thread():thread.join(timeout=2)
        with self._transport_lock:
            if self._session:
                if self._session.close() is False:
                    self.connected=False
                    raise RuntimeError("原生清理尚未完成；会话已隔离，禁止再次挂载。")
            self._session=None;self.connected=False


def build_adapter(backend,config,on_message,on_status=None):
    if backend not in ('auto','native','',None):raise RuntimeError('macOS 版仅支持 Wemac-auto 内部函数后端。')
    if not detect_wechat_backends()['native']:raise RuntimeError('请安装 Wemac-auto 与 Frida 原生运行依赖。')
    return NativeWeChatAdapter(config,on_message,on_status)


def adapter_capabilities():return {**detect_wechat_backends(),'preferred':'native'}
