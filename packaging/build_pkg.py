"""Reproducible standalone arm64 app and a privacy-clean macOS Installer package."""
from pathlib import Path
import argparse,hashlib,json,os,plistlib,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parent.parent
P=ROOT/'packaging';WORK=P/'.build';DIST=ROOT/'dist';PAYLOAD=P/'payload'

def run(args):subprocess.run([str(x) for x in args],check=True)

def build(*,online=False,sdk_only=False):
    WORK.mkdir(exist_ok=True);DIST.mkdir(exist_ok=True)
    sdk=PAYLOAD/'sdk'
    if sdk.exists():shutil.rmtree(sdk)
    shutil.copytree(ROOT/'src',sdk/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for f in ['pyproject.toml','LICENSE','README.md','README.zh-CN.md']:shutil.copy2(ROOT/f,sdk/f)
    shutil.copytree(ROOT/'docs',sdk/'docs')
    shutil.copytree(ROOT/'examples',sdk/'examples',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(ROOT/'bot/docs',sdk/'bot-docs')
    for name in ['requirements-macos.txt','requirements-character-voice.lock','requirements-reference-audio.txt']:
        shutil.copy2(ROOT/'bot'/name,sdk/name)
    license_dir=PAYLOAD/'licenses';license_dir.mkdir(exist_ok=True)
    for name in ['OPENCORE-AMR-LICENSE','OPENCORE-AMR-NOTICE']:
        shutil.copy2(ROOT/'bot/vendor'/name,license_dir/name)
    bundle_payload=WORK/'online-payload' if online else PAYLOAD
    if sdk_only:
        bundle_payload=WORK/'sdk-payload'
        if bundle_payload.exists():shutil.rmtree(bundle_payload)
        shutil.copytree(PAYLOAD,bundle_payload,ignore=shutil.ignore_patterns('character-voice.tar.gz','character-voice.json','online-models.json'))
        (bundle_payload/'product.json').write_text(json.dumps({'product':'sdk'}))
    if online:
        if bundle_payload.exists():shutil.rmtree(bundle_payload)
        shutil.copytree(PAYLOAD,bundle_payload,ignore=shutil.ignore_patterns('character-voice.tar.gz','character-voice.json'))
        archive=WORK/'voice-runtime.tar.gz'
        if not archive.is_file():raise RuntimeError('Prepare the portable voice-runtime.tar.gz first')
        shutil.copy2(archive,bundle_payload/'character-voice.tar.gz')
        staging=WORK/'voice-staging'
        size=sum(p.stat().st_size for name in ['runtime','GPT-SoVITS'] for p in (staging/name).rglob('*') if p.is_file() and not p.is_symlink())
        (bundle_payload/'character-voice.json').write_text(json.dumps({'uncompressed_bytes':size,'includes_personal_references':False}))
    elif not sdk_only and (PAYLOAD/'online-models.json').exists():
        # Offline builds must never accidentally download after extraction.
        bundle_payload=WORK/'offline-payload'
        if bundle_payload.exists():shutil.rmtree(bundle_payload)
        shutil.copytree(PAYLOAD,bundle_payload,ignore=shutil.ignore_patterns('online-models.json'))
    identity='com.wemac.auto.installer.sdk' if sdk_only else 'com.wemac.auto.installer.bot'
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed','--name','Wemac-auto 安装助手',
        '--target-arch','arm64','--osx-bundle-identifier',identity,
        '--distpath',WORK/'apps','--workpath',WORK/'pyinstaller','--specpath',WORK,
        '--paths',ROOT/'bot','--paths',ROOT/'src','--paths',P,
        '--icon',ROOT/'bot/.runtime/什亭之匣.app/Contents/Resources/Arona.icns',
        '--collect-submodules','app','--collect-submodules','wechat_aumac','--collect-all','frida',
        '--collect-all','keyring','--hidden-import','AppKit','--hidden-import','Foundation',
        '--hidden-import','run','--hidden-import','av','--collect-all','imageio_ffmpeg',
        '--add-data',str(bundle_payload)+':installer_payload',
        '--add-data',str(ROOT/'bot/assets')+':assets',
        '--add-data',str(ROOT/'bot/data/stickers')+':data/stickers',
        '--add-data',str(ROOT/'bot/scripts')+':scripts',
        '--add-data',str(ROOT/'bot/app')+':source/app',P/'entry.py']
    run(command)
    app=WORK/'apps/Wemac-auto 安装助手.app'
    display='Wemac-auto SDK 安装助手' if sdk_only else ('Aronabot-MacOS 安装助手' if online else 'Wemac-auto 安装助手')
    if display!='Wemac-auto 安装助手':
        renamed=app.with_name(display+'.app')
        if renamed.exists():shutil.rmtree(renamed)
        app.rename(renamed);app=renamed
    infofile=app/'Contents/Info.plist';info=plistlib.loads(infofile.read_bytes())
    version='0.3.1' if (online or sdk_only) else '0.3.0'
    info.update(CFBundleShortVersionString=version,CFBundleVersion='301' if online else '300',LSMinimumSystemVersion='13.0')
    infofile.write_bytes(plistlib.dumps(info))
    run(['/usr/bin/codesign','--force','--deep','--sign','-','--timestamp=none',app])
    run(['/usr/bin/codesign','--verify','--deep','--strict',app])
    stage=WORK/'pkgroot'
    if stage.exists():shutil.rmtree(stage)
    (stage/'Applications').mkdir(parents=True,exist_ok=True)
    target=stage/'Applications'/app.name
    if target.exists():shutil.rmtree(target)
    run(['/usr/bin/ditto',app,target])
    scripts=WORK/'pkg-scripts';scripts.mkdir(exist_ok=True)
    post=scripts/'postinstall'
    post.write_text('''#!/bin/sh
# Launch as the logged-in user, never as root; all app setup is user-scoped.
console_user=$(/usr/bin/stat -f %Su /dev/console)
if [ "$console_user" != "root" ] && [ "$console_user" != "loginwindow" ]; then
  console_uid=$(/usr/bin/id -u "$console_user")
  /bin/launchctl asuser "$console_uid" /usr/bin/sudo -u "$console_user" /usr/bin/open "/Applications/INSTALLER_APP_NAME" || true
fi
exit 0
'''.replace('INSTALLER_APP_NAME',app.name));post.chmod(0o755)
    component=WORK/'Wemac-auto-component.pkg'
    component_info=WORK/'components.plist'
    run(['/usr/bin/pkgbuild','--analyze','--root',stage,component_info])
    components=plistlib.loads(component_info.read_bytes())
    for item in components:
        # Never relocate an embedded Python framework over a system/user one.
        item['BundleIsRelocatable']=False
        item['BundleIsVersionChecked']=False
    component_info.write_bytes(plistlib.dumps(components))
    run(['/usr/bin/pkgbuild','--root',stage,'--component-plist',component_info,'--scripts',scripts,'--identifier',identity,
         '--version',version,'--install-location','/',component])
    resources=WORK/'resources';resources.mkdir(exist_ok=True)
    (resources/'welcome.html').write_text('''<html><meta charset="utf-8"><body><h2>Wemac-auto 0.3.0</h2><p>Apple Silicon / macOS 13 或更新。系统安装完成后会打开安装助手，选择自定义安装目录和本机原版微信，点击一次开始完成复制、独立身份及逐组件重签名，并显示进度。</p><p>需要微信 4.2.0（270348）；不会复制账号数据，也不会停止或重启任何微信进程。此包不包含腾讯微信本体、私人录音、聊天、账号凭据或 API Key。</p><p>后台 SDK、机器人界面、媒体发送编码器均包含。联网模型需要配置自己的 API。角色公开模型与离线推理环境已内置；个人参考录音需要另行配置，默认近似音使用在线服务。需要允许 macOS 正常提示的权限。</p><p>此安装包未使用 Developer ID 公证，不会自动更改系统安全设置。</p></body></html>''')
    if online:
        welcome=resources/'welcome.html'
        welcome.write_text(welcome.read_text().replace('0.3.0','0.3.1 在线安装版').replace('角色公开模型与离线推理环境已内置','Python 和语音推理环境已内置，约 1.2 GB 公开模型会在安装时自动联网下载并校验，无需手动安装依赖'))
    distribution=WORK/'Distribution.xml'
    distribution.write_text('''<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2"><title>Wemac-auto</title>
<options customize="never" require-scripts="false" hostArchitectures="arm64"/>
<domains enable_anywhere="false" enable_currentUserHome="false" enable_localSystem="true"/>
<welcome file="welcome.html" mime-type="text/html"/>
<choices-outline><line choice="main"/></choices-outline>
<choice id="main" title="Wemac-auto 安装助手"><pkg-ref id="com.wemac.auto.installer"/></choice>
<pkg-ref id="com.wemac.auto.installer" version="0.3.0">Wemac-auto-component.pkg</pkg-ref>
</installer-gui-script>''')
    if online or sdk_only:distribution.write_text(distribution.read_text().replace('version="0.3.0"','version="0.3.1"'))
    distribution.write_text(distribution.read_text().replace('com.wemac.auto.installer',identity))
    if sdk_only:
        welcome=resources/'welcome.html'
        welcome.write_text('<html><meta charset="utf-8"><body><h2>Wemac-auto SDK 0.3.1</h2><p>Apple Silicon / macOS 13+，微信 4.2.0（270348）。安装 SDK、独立命令行运行环境与微信副本配置；安装后打开助手选择目录并显示复制、重签名进度。不下载机器人语音模型，不包含账号或密钥。</p><p>本包未做 Developer ID 签名与公证。</p></body></html>')
    pkg=DIST/('Wemac-auto-0.3.1-arm64-sdk.pkg' if sdk_only else ('Aronabot-MacOS-0.3.1-arm64-online.pkg' if online else 'Wemac-auto-0.3.0-arm64.pkg'))
    run(['/usr/bin/productbuild','--distribution',distribution,'--package-path',WORK,'--resources',resources,pkg])
    digest=hashlib.sha256(pkg.read_bytes()).hexdigest()
    if (online or sdk_only) and pkg.stat().st_size>=500_000_000:raise RuntimeError(f'Package exceeds 500 MB: {pkg.stat().st_size} bytes')
    (DIST/(pkg.name+'.sha256')).write_text(digest+'  '+pkg.name+'\n')
    print('PACKAGE',pkg,'SHA256',digest,flush=True)
if __name__=='__main__':
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group();group.add_argument('--online',action='store_true');group.add_argument('--sdk-only',action='store_true')
    args=parser.parse_args();build(online=args.online,sdk_only=args.sdk_only)
