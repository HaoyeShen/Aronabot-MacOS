"""Pinned public model downloads, resumable cache and verified final copies."""
from pathlib import Path
import hashlib,json,shutil,ssl,time,urllib.request,urllib.parse
import certifi

def sha256(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for data in iter(lambda:f.read(4*1024*1024),b''):h.update(data)
 return h.hexdigest()

def download_asset(asset,cache,progress=lambda n:None):
 url=asset['url'];parsed=urllib.parse.urlparse(url)
 if parsed.scheme!='https' or parsed.hostname!='huggingface.co':raise ValueError('Untrusted model origin')
 digest=asset['sha256'];size=int(asset['size'])
 if len(digest)!=64 or any(x not in '0123456789abcdef' for x in digest) or size<=0:raise ValueError('Invalid model fingerprint')
 cache=Path(cache);cache.mkdir(parents=True,exist_ok=True);final=cache/digest;partial=cache/(digest+'.part')
 if final.exists() and final.stat().st_size==size and sha256(final)==digest:
  progress(size);return final
 ctx=ssl.create_default_context(cafile=certifi.where())
 for attempt in range(3):
  try:
   offset=partial.stat().st_size if partial.exists() else 0
   if offset>size:partial.unlink();offset=0
   if offset<size:
    req=urllib.request.Request(url,headers={'Range':f'bytes={offset}-'} if offset else {})
    with urllib.request.urlopen(req,context=ctx,timeout=45) as response:
     resumed=offset and response.status==206
     if resumed and not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise ValueError('Invalid download range')
     if not resumed:offset=0
     with partial.open('ab' if resumed else 'wb') as out:
      while block:=response.read(1024*1024):
       if offset+len(block)>size:raise ValueError('Model exceeds expected size')
       out.write(block);offset+=len(block);progress(offset)
   if partial.stat().st_size!=size or sha256(partial)!=digest:
    partial.unlink(missing_ok=True);raise ValueError('Model fingerprint mismatch')
   partial.replace(final);return final
  except Exception:
   if attempt==2:raise
   time.sleep(1+attempt)

def install_models(root,manifest,progress=lambda n,s:None,cache=None):
 root=Path(root).resolve();items=json.loads(Path(manifest).read_text())['assets']
 total=sum(a['size'] for a in items);done=0
 cache=Path(cache) if cache else Path.home()/'Library/Caches/Wemac-auto/Installer/models'
 for a in items:
  rel=Path(a['file']);target=(root/rel).resolve()
  if rel.is_absolute() or not target.is_relative_to(root) or not rel.parts or rel.parts[0]!='models':raise ValueError('Invalid model destination')
  def update(current):progress(90+int(8*(done+current)/max(1,total)),f'下载语音模型 {(done+current)/1e6:.1f} / {total/1e6:.1f} MB')
  cached=download_asset(a,cache,update);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(cached,target)
  if sha256(target)!=a['sha256']:raise ValueError('Installed model fingerprint mismatch')
  done+=a['size']
 progress(98,'全部公开模型下载与 SHA-256 校验完成')
