import hashlib,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import online_models as m

class Response(io.BytesIO):
 status=200
 headers={}
class Interrupted(Response):
 def read(self,n=-1):
  if self.tell():raise TimeoutError('fixture interruption')
  return super().read(3)
class Tests(unittest.TestCase):
 def asset(self):
  return {'url':'https://huggingface.co/repo/resolve/pinned/file','size':6,'sha256':hashlib.sha256(b'abcdef').hexdigest(),'file':'models/file'}
 def test_resume_and_cached_verification(self):
  with tempfile.TemporaryDirectory() as td:
   resumed=Response(b'def');resumed.status=206;resumed.headers={'Content-Range':'bytes 3-5/6'}
   with patch.object(m.urllib.request,'urlopen',side_effect=[Interrupted(b'abcdef'),resumed]) as request,patch.object(m.time,'sleep'):
    p=m.download_asset(self.asset(),td);self.assertEqual(p.read_bytes(),b'abcdef')
    self.assertEqual(request.call_args.args[0].get_header('Range'),'bytes=3-')
   with patch.object(m.urllib.request,'urlopen') as request:
    self.assertEqual(m.download_asset(self.asset(),td),p);request.assert_not_called()
 def test_bad_hash_not_installed(self):
  with tempfile.TemporaryDirectory() as td:
   with patch.object(m.urllib.request,'urlopen',side_effect=lambda *a,**k:Response(b'xxxxxx')),patch.object(m.time,'sleep'):
    with self.assertRaises(ValueError):m.download_asset(self.asset(),td)
   self.assertFalse((Path(td)/self.asset()['sha256']).exists())
 def test_destination_escape_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);a=self.asset();a['file']='../escape';manifest=root/'manifest.json';manifest.write_text(json.dumps({'assets':[a]}))
   with patch.object(m,'download_asset') as download:
    with self.assertRaises(ValueError):m.install_models(root/'target',manifest)
    download.assert_not_called()
 def test_untrusted_host_rejected(self):
  a=self.asset();a['url']='https://example.org/model'
  with self.assertRaises(ValueError):m.download_asset(a,'unused')
if __name__=='__main__':unittest.main()
