"""Exercise real copy/sign/relocation using a disposable fake WeChat, never a live one."""
from pathlib import Path
from unittest.mock import patch
import tempfile,plistlib,shutil,subprocess,json,os,hashlib
import installer_core as core
root=Path(__file__).resolve().parent.parent
assistant=root/'packaging/.build/apps/Wemac-auto 安装助手.app';payload=root/'packaging/payload'
with tempfile.TemporaryDirectory(prefix='wemac-install-fixture-') as td:
    base=Path(td);source=base/'WeChat.app'
    (source/'Contents/MacOS').mkdir(parents=True);(source/'Contents/Resources').mkdir()
    (source/'Contents/Frameworks').mkdir()
    info={'CFBundleIdentifier':core.OLD_ID,'CFBundleVersion':'270348','CFBundleExecutable':'WeChat','CFBundlePackageType':'APPL'}
    (source/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    shutil.copyfile('/usr/bin/true',source/'Contents/MacOS/WeChat');(source/'Contents/MacOS/WeChat').chmod(0o755)
    for name in ['wechat.dylib','MultiMediaDyn']:shutil.copy2(payload/'libaumac_completion.dylib',source/'Contents/Resources'/name)
    stages=[]
    with patch.object(core,'validate_source',return_value=source),patch.object(core,'signing_plan',return_value=[(Path('.'),core.NEW_ID,{})]),patch('pathlib.Path.home',return_value=base/'fake-home'):
        installed=core.install(source,base/'自定义安装目录',assistant,payload,base/'data',lambda n,s:stages.append((n,s)))
    assert stages[-1][0]==100
    assert plistlib.loads((source/'Contents/Info.plist').read_bytes())['CFBundleIdentifier']==core.OLD_ID
    assert plistlib.loads((installed/'Contents/Info.plist').read_bytes())['CFBundleIdentifier']=='com.wemac.auto.arona'
    profile=json.loads((base/'data/native-profile-isolated.json').read_text())
    assert str(base/'自定义安装目录') in profile['app']
    assert Path(profile['corePath']).is_file() and Path(profile['nativeDatabase']['bridge']['path']).is_file()
    check=subprocess.run([str(installed/'Contents/MacOS/Wemac-auto 安装助手'),'--package-check'],env=dict(os.environ,ARONA_DATA_DIR=str(base/'data')),capture_output=True,text=True,timeout=45)
    print(check.stdout,check.stderr[-1000:]);assert check.returncode==0
    voice=base/'data/character_voice'
    if voice.exists():
        reference=Path.home()/'Library/Application Support/WemacAuto/Arona/character_voice/references/arona/reference.wav'
        if reference.is_file():
            (voice/'profiles').mkdir();shutil.copy2(reference,voice/'reference.wav')
            profile={'character':'arona','reference_audio':'reference.wav',
                     'transcript':'嗯，是不是要下雨啊？',
                     'reference_sha256':hashlib.sha256(reference.read_bytes()).hexdigest(),
                     't2s_weights':'models/base/s1-v2.ckpt',
                     'vits_weights':'models/arona/normal_e8_s1536.pth'}
            (voice/'profiles/arona.json').write_text(json.dumps(profile))
            worker=payload.parent.parent/'bot/scripts/character_voice_worker.py'
            # This local-only reference is added after installation exclusively
            # inside the disposable fixture. It is never added to the package.
            synth=subprocess.run([str(voice/'runtime/bin/python3'),str(worker),'--character','arona','--text','老师，今天也请多指教。','--output',str(base/'preview.wav')],
                env=dict(os.environ,ARONA_CHARACTER_VOICE_ROOT=str(voice)),capture_output=True,text=True,timeout=90)
            if synth.returncode:print(synth.stderr[-2000:])
            assert synth.returncode==0 and (base/'preview.wav').stat().st_size>1000
            print('RELOCATED_OFFLINE_VOICE_SYNTHESIS_PASS')
    print('FULL_INSTALL_FIXTURE_PASS: Unicode directory, real copy/sign, relocated profile, standalone dependency check; no live WeChat touched')
    print('PROGRESS',','.join(str(n) for n,_ in stages))
