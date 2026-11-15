"""Build the pinned Skype SILK reference codec locally (no service or account data)."""
import concurrent.futures, hashlib, shutil, subprocess, sys, tarfile, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.paths import DATA
ROOT=Path(__file__).resolve().parents[1]
archive=ROOT/'vendor/silk-source.tar.gz'
if hashlib.sha256(archive.read_bytes()).hexdigest()!='8b17b40f8ff0ebf523b52d7e0417570ddd56e365db3e02d4e5fa61762fb3e1e2':
    raise SystemExit('SILK source fingerprint changed')
with tempfile.TemporaryDirectory(prefix='wemac-silk-') as tmp:
    root=Path(tmp)
    with tarfile.open(archive) as package:package.extractall(root,filter='data')
    source=root/'silk';files=sorted((source/'src').glob('*.c'))
    def compile(item):
        index,path=item;obj=root/f'{index}.o'
        subprocess.run(['clang','-mmacosx-version-min=13.0','-O2','-fPIC','-fwrapv','-I'+str(source/'src'),'-I'+str(source/'interface'),'-c',str(path),'-o',str(obj)],check=True,capture_output=True)
        return obj
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:objects=list(pool.map(compile,enumerate(files)))
    destination=DATA/'lib';destination.mkdir(parents=True,exist_ok=True)
    library=destination/'libwemac-silk.dylib'
    subprocess.run(['clang','-mmacosx-version-min=13.0','-dynamiclib',*[str(p) for p in objects],'-o',str(library)],check=True)
    subprocess.run(['codesign','--force','--sign','-','--timestamp=none',str(library)],check=True)
    shutil.copy2(ROOT/'vendor/SILK-LICENSE',destination/'SILK-LICENSE')
    print('Local SILK codec installed:',library)
