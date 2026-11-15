"""Stage public weights and a relocatable Python; never include personal references."""
from pathlib import Path
import json,shutil,subprocess,tarfile
ROOT=Path(__file__).resolve().parent.parent
voice=Path.home()/'Library/Application Support/WemacAuto/Arona/character_voice'
work=ROOT/'packaging/.build/voice-staging';work.mkdir(parents=True,exist_ok=True)
python=Path(subprocess.check_output([str(voice/'runtime/bin/python3'),'-c','import sys;print(sys.base_prefix)'],text=True).strip())
ignore=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store','.git','*.log')
shutil.copytree(python,work/'runtime',dirs_exist_ok=True,ignore=ignore)
shutil.copytree(voice/'runtime/lib/python3.11/site-packages',work/'runtime/lib/python3.11/site-packages',dirs_exist_ok=True,ignore=ignore)
shutil.copytree(voice/'GPT-SoVITS',work/'GPT-SoVITS',dirs_exist_ok=True,ignore=ignore)
for folder in ['arona','plana','base']:
 shutil.copytree(voice/'models'/folder,work/'models'/folder,dirs_exist_ok=True,ignore=ignore)
for name in ['model_manifest.json','source-manifest.json']:
 if (voice/name).exists():shutil.copy2(voice/name,work/name)
(work/'README.txt').write_text('Public model resources; personal references and character profiles are intentionally excluded. See sdk/bot-docs/character-voice.md.\nSources: https://github.com/RVC-Boss/GPT-SoVITS https://huggingface.co/lj1995/GPT-SoVITS https://huggingface.co/xingguangcuican6666/arona-sovits (GPL-3.0) https://huggingface.co/xingguangcuican6666/plana-gptsovits-v2 (MIT)\n')
archive=ROOT/'packaging/payload/character-voice.tar.gz'
(archive.parent/'character-voice.json').write_text(json.dumps({
    'uncompressed_bytes':sum(p.stat().st_size for p in work.rglob('*') if p.is_file() and not p.is_symlink()),
    'includes_personal_references':False,
}))
with tarfile.open(archive,'w:gz',compresslevel=1) as tar:
 for item in sorted(work.iterdir()):tar.add(item,arcname=item.name,filter=lambda info:None if '__pycache__' in info.name else info)
print('PUBLIC_VOICE_ARCHIVE',archive.stat().st_size,flush=True)
