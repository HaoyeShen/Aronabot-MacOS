"""Verified installed emoji catalog exposed by the native WeChat session."""
from __future__ import annotations
import hashlib,json,threading
from pathlib import Path
from .paths import DATA

class NativeStickers:
    def __init__(self,session,folder=None):
        self.session=session;self.folder=Path(folder or DATA/'images/native_stickers')
        self.entries={};self.pages=[];self.signature='';self._lock=threading.RLock()
    def catalog(self):
        with self._lock:
            if not callable(getattr(self.session,'get_installed_stickers',None)):
                raise RuntimeError('当前原生 profile 尚未提供已安装表情目录接口。')
            result=self.session.get_installed_stickers()
            if not result.get('complete'):raise RuntimeError('原生表情目录不完整，不能用于模型选择。')
            entries={};pages=[]
            for page in result['pages']:
                items=[]
                for item in page['items']:
                    digest=str(item.get('md5','')).lower()
                    if len(digest)!=32 or any(c not in '0123456789abcdef' for c in digest):continue
                    identity='wxemote_'+digest
                    if identity in entries:
                        entry=entries[identity]
                        for location in item.get('locations',[]):
                            if location not in entry.setdefault('locations',[]):entry['locations'].append(location)
                    else:
                        entry=entries.setdefault(identity,{**item,'id':identity,'md5':digest,'kind':'wechat_native','enabled':True})
                    items.append({'id':identity,'name':entry['name'],'order':len(items)+1})
                pages.append({'id':page['id'],'name':page['name'],'items':items})
            self.entries,self.pages=entries,pages
            self.signature=hashlib.sha256(json.dumps(pages,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            return {'complete':True,'signature':self.signature,'count':len(entries),'page_count':len(pages),'pages':pages,'unavailable':result.get('unavailable',[])}
    def preview(self,identity):
        with self._lock:
            entry=self.entries.get(identity)
            if not entry:raise ValueError('表情不在本次已核对的全页目录中。')
            self.folder.mkdir(parents=True,exist_ok=True)
            path=Path(self.session.download_sticker(entry,self.folder))
            if hashlib.md5(path.read_bytes()).hexdigest()==entry['md5']:
                proof={'transcoded':False,'verified_md5':True}
            elif hasattr(self.session,'verify_sticker_file'):
                proof=self.session.verify_sticker_file(entry,path)
                if not isinstance(proof,dict) or proof.get('native_decoded') is not True or proof.get('source_md5')!=entry['md5']:
                    raise ValueError('原生表情转换来源未通过核对。')
            else:
                if hashlib.md5(path.read_bytes()).hexdigest()!=entry['md5']:raise ValueError('原生表情资源 MD5 不匹配。')
                proof={'transcoded':False}
            return path,{**entry,'native_resource':proof},False
    def preview_strip(self,identity):
        from PIL import Image,ImageOps
        path,entry,thumb=self.preview(identity)
        dest=self.folder/(entry['md5']+'.preview.png')
        with Image.open(path) as source:
            frames=[];count=getattr(source,'n_frames',1)
            for index in sorted({round(i*(count-1)/min(3,count-1)) if count>1 else 0 for i in range(min(4,count))}):
                source.seek(index);frames.append(ImageOps.pad(source.convert('RGBA'),(240,240),color='white'))
            strip=Image.new('RGBA',(240*len(frames),240),'white')
            for index,frame in enumerate(frames):strip.paste(frame,(240*index,0),frame)
            strip.convert('RGB').save(dest)
        return dest,entry,thumb
