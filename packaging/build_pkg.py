"""Reproducible standalone arm64 app and a privacy-clean macOS Installer package."""
from pathlib import Path
import hashlib,json,os,plistlib,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parent.parent
P=ROOT/'packaging';WORK=P/'.build';DIST=ROOT/'dist';PAYLOAD=P/'payload'

def run(args):subprocess.run([str(x) for x in args],check=True)

def build():
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
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed','--name','Wemac-auto 安装助手',
        '--target-arch','arm64','--osx-bundle-identifier','com.wemac.auto.installer',
        '--distpath',WORK/'apps','--workpath',WORK/'pyinstaller','--specpath',WORK,
        '--paths',ROOT/'bot','--paths',ROOT/'src','--paths',P,
        '--icon',ROOT/'bot/.runtime/什亭之匣.app/Contents/Resources/Arona.icns',
        '--collect-submodules','app','--collect-submodules','wechat_aumac','--collect-all','frida',
        '--collect-all','keyring','--hidden-import','AppKit','--hidden-import','Foundation',
        '--hidden-import','run','--hidden-import','av','--collect-all','imageio_ffmpeg',
        '--add-data',str(PAYLOAD)+':installer_payload',
        '--add-data',str(ROOT/'bot/assets')+':assets',
        '--add-data',str(ROOT/'bot/data/stickers')+':data/stickers',
        '--add-data',str(ROOT/'bot/scripts')+':scripts',
        '--add-data',str(ROOT/'bot/app')+':source/app',P/'entry.py']
    run(command)
    app=WORK/'apps/Wemac-auto 安装助手.app'
    infofile=app/'Contents/Info.plist';info=plistlib.loads(infofile.read_bytes())
    info.update(CFBundleShortVersionString='0.3.0',CFBundleVersion='300',LSMinimumSystemVersion='13.0')
    infofile.write_bytes(plistlib.dumps(info))
    run(['/usr/bin/codesign','--force','--deep','--sign','-','--timestamp=none',app])
    run(['/usr/bin/codesign','--verify','--deep','--strict',app])
    stage=WORK/'pkgroot';(stage/'Applications').mkdir(parents=True,exist_ok=True)
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
  /bin/launchctl asuser "$console_uid" /usr/bin/sudo -u "$console_user" /usr/bin/open "/Applications/Wemac-auto 安装助手.app" || true
fi
exit 0
''');post.chmod(0o755)
    component=WORK/'Wemac-auto-component.pkg'
    component_info=WORK/'components.plist'
    run(['/usr/bin/pkgbuild','--analyze','--root',stage,component_info])
    components=plistlib.loads(component_info.read_bytes())
    for item in components:
        # Never relocate an embedded Python framework over a system/user one.
        item['BundleIsRelocatable']=False
        item['BundleIsVersionChecked']=False
    component_info.write_bytes(plistlib.dumps(components))
    run(['/usr/bin/pkgbuild','--root',stage,'--component-plist',component_info,'--scripts',scripts,'--identifier','com.wemac.auto.installer',
         '--version','0.3.0','--install-location','/',component])
    resources=WORK/'resources';resources.mkdir(exist_ok=True)
    (resources/'welcome.html').write_text('''<html><meta charset="utf-8"><body><h2>Wemac-auto 0.3.0</h2><p>Apple Silicon / macOS 13 或更新。系统安装完成后会打开安装助手，选择自定义安装目录和本机原版微信，点击一次开始完成复制、独立身份及逐组件重签名，并显示进度。</p><p>需要微信 4.2.0（270348）；不会复制账号数据，也不会停止或重启任何微信进程。此包不包含腾讯微信本体、私人录音、聊天、账号凭据或 API Key。</p><p>后台 SDK、机器人界面、媒体发送编码器均包含。联网模型需要配置自己的 API。角色公开模型与离线推理环境已内置；个人参考录音需要另行配置，默认近似音使用在线服务。需要允许 macOS 正常提示的权限。</p><p>此安装包未使用 Developer ID 公证，不会自动更改系统安全设置。</p></body></html>''')
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
    pkg=DIST/'Wemac-auto-0.3.0-arm64.pkg'
    run(['/usr/bin/productbuild','--distribution',distribution,'--package-path',WORK,'--resources',resources,pkg])
    digest=hashlib.sha256(pkg.read_bytes()).hexdigest()
    (DIST/(pkg.name+'.sha256')).write_text(digest+'  '+pkg.name+'\n')
    print('PACKAGE',pkg,'SHA256',digest,flush=True)
if __name__=='__main__':build()
