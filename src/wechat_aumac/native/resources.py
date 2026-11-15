"""Export cached artwork with WeChat's account-bound native resource getter."""
from __future__ import annotations
import hashlib,json,re,threading,tempfile
from pathlib import Path
from importlib.resources import files

class NativeResources:
    def __init__(self,session):
        if session._session is None or not session.profile.get('nativeResources'):
            raise RuntimeError('This profile has no native cached-resource ABI')
        self.session=session;self._lock=threading.RLock()
        rows=[r for r in session._database().catalog() if r['name']=='emoticon.db']
        if len(rows)!=1:raise RuntimeError('The active account resource directory is ambiguous')
        self.root=Path(rows[0]['path']).parents[2].resolve()
        self.owner=session.identity()['user_id']
        if not self.root.name.startswith(self.owner+'_'):raise RuntimeError('Resource directory belongs to another account')
        config={k:session.profile[k] for k in ('corePath','functions')};config['accountRoot']=str(self.root)
        script=session._session.create_script('const CONFIG='+json.dumps(config)+';\n'+files(__package__).joinpath('resource_agent.js').read_text())
        errors=[]
        script.on('message',lambda message,data:errors.append(message.get('description','Resource agent error')) if message.get('type')=='error' else None)
        try:
            script.load()
            if errors:raise RuntimeError('; '.join(errors))
        except Exception:
            script.unload();raise
        self._script=script
    def close(self):
        with self._lock:
            if self._script:
                self._script.exports_sync.dispose()
                self._script.unload()
                self._script=None
    def _decode(self,path,offset=0,length=0,material=None,variant=0):
        if self.session.identity()['user_id']!=self.owner:raise RuntimeError('Account changed; reconnect resource reader')
        path=path.resolve()
        if not path.is_relative_to(self.root):raise ValueError('Cached resource outside the selected account')
        with self._lock:result=self._script.exports_sync.decode(str(path),offset,length,material,variant)
        return bytes(result['bytes'])
    @staticmethod
    def _verified(data,digest):
        if hashlib.md5(data).hexdigest()==digest:return data
        pad=data[-1] if data else 0
        if 0<pad<=16 and data[-pad:]==bytes([pad])*pad:
            candidate=data[:-pad]
            if hashlib.md5(candidate).hexdigest()==digest:return candidate
        raise ValueError('Decoded artwork does not match the exact message/sticker MD5')
    def download_sticker(self,entry,directory):
        digest=str(entry.get('md5') or '').lower()
        if not re.fullmatch('[a-f0-9]{32}',digest):raise ValueError('Expected a verified sticker MD5')
        folder=Path(directory).expanduser().resolve();folder.mkdir(parents=True,exist_ok=True)
        destination=folder/(digest+'.image')
        if destination.is_file():
            try:self.verify_sticker_file(entry,destination);return destination
            except ValueError:destination.unlink()
        candidates=[]
        for location in entry.get('locations',[]):
            if location.get('page') in (None,'favorite'):continue
            package=hashlib.md5(location['page'].encode()).hexdigest()
            path=self.root/'business/emoticon/PersistStore'/package[:2]/package
            candidates.append((path,int(location.get('offset') or 0),int(location.get('size') or 0)))
        candidates.append((self.root/'business/emoticon/Persist'/digest[:2]/digest,0,0))
        candidates.extend((p,0,0) for p in (self.root/'cache').glob('????-??/Emoticon/'+digest[:2]+'/'+digest))
        failures=[]
        for path,offset,size in candidates:
            if not path.is_file():continue
            try:
                if path.stat().st_size>64*1024*1024:raise ValueError('Resource container too large')
                data=self._decode(path,offset,size)
                try:
                    data=self._verified(data,digest)
                    destination.write_bytes(data);return destination
                except ValueError:
                    if not data.startswith(b'wxgf'):raise
                codec=self.session.profile['nativeResources'].get('wxgfCodec')
                if not codec:raise ValueError('Native WXGF codec is not pinned')
                pad=data[-1] if data else 0
                if 0<pad<=16 and data[-pad:]==bytes([pad])*pad:data=data[:-pad]
                from .wxgf import convert
                with tempfile.TemporaryDirectory(prefix='wemac-wxgf-') as temp:
                    source=Path(temp)/'source.wxgf';source.write_bytes(data)
                    report=convert(source,destination,codec)
                report.update(source_md5=digest,resource_location=str(path.relative_to(self.root)))
                destination.with_suffix(destination.suffix+'.native.json').write_text(json.dumps(report))
                return destination
            except Exception as exc:failures.append(type(exc).__name__)
        # Non-store emoji may retain their own CDN encryption instead of the
        # installed-pack cipher. Keep this material inside the WeChat process.
        database=self.session._database();material=None
        try:
            with database._lock:material=database._script.exports_sync.emoji_material(digest)
            for path,offset,size in candidates:
                if not path.is_file() or offset:continue
                for variant in (0,1,2):
                    try:
                        data=self._verified(self._decode(path,0,0,material,variant),digest)
                        destination.write_bytes(data);return destination
                    except Exception:continue
        except Exception as exc:failures.append(type(exc).__name__)
        finally:
            if material:
                with database._lock:database._script.exports_sync.release_material(material['id'])
        raise RuntimeError('Exact cached sticker unavailable through native resource decoding: '+','.join(failures))

    def verify_sticker_file(self,entry,path):
        from .wxgf import verify
        return verify(path,str(entry.get('md5') or '').lower(),
                      self.session.profile['nativeResources'].get('wxgfCodec') or {})
