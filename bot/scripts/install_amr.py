"""Build the bundled Apache-2.0 OpenCORE AMR source for this Mac."""
from __future__ import annotations
import concurrent.futures,hashlib,re,shutil,subprocess,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.paths import DATA
ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/'vendor/opencore-amr-source.tar.gz'
EXPECTED='ac1957694e8501e1ca1aee0929e736865c175bad55fa8429931e8e35c3155ad1'
if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()!=EXPECTED:raise SystemExit('Bundled OpenCORE source fingerprint changed')
with tempfile.TemporaryDirectory(prefix='wemac-amr-build-') as tmp:
    import tarfile
    folder=Path(tmp)
    with tarfile.open(ARCHIVE) as archive:archive.extractall(folder,filter='data')
    source=next(folder.glob('opencore-amr-*'));base=source/'opencore/codecs_v2/audio/gsm_amr'
    variables={'DEC_SRC_DIR':base/'amr_nb/dec/src','ENC_SRC_DIR':base/'amr_nb/enc/src','COMMON_SRC_DIR':base/'amr_nb/common/src'}
    make='\n'.join(l for l in (source/'amrnb/Makefile.am').read_text().splitlines() if not l.lstrip().startswith('#'))
    files=[source/'amrnb/wrapper.cpp']
    files.extend(variables[name]/file for name,file in re.findall(r'\$\((DEC_SRC_DIR|ENC_SRC_DIR|COMMON_SRC_DIR)\)/([A-Za-z0-9_]+\.cpp)',make))
    files=list(dict.fromkeys(files));include=[source/'oscl',variables['DEC_SRC_DIR'],base/'amr_nb/common/include',base/'amr_nb/dec/include',base/'common/dec/include',variables['ENC_SRC_DIR']]
    build=folder/'objects';build.mkdir()
    def compile(item):
        index,path=item;obj=build/f'{index}.o'
        subprocess.run(['clang++','-std=c++11','-Os','-fPIC',*[arg for p in include for arg in ('-I',str(p))],'-c',str(path),'-o',str(obj)],check=True,capture_output=True)
        return obj
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:objects=list(pool.map(compile,enumerate(files)))
    destination=DATA/'lib';destination.mkdir(parents=True,exist_ok=True)
    library=destination/'libopencore-amrnb.dylib'
    subprocess.run(['clang++','-dynamiclib',*[str(p) for p in objects],'-o',str(library)],check=True,capture_output=True)
    for name in ('OPENCORE-AMR-LICENSE','OPENCORE-AMR-NOTICE'):shutil.copy2(ROOT/'vendor'/name,destination/name)
    print('AMR encoder installed:',library,'sources:',len(files))
