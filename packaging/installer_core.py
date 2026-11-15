"""Transactional, offline installation. Never launches/stops WeChat or copies accounts."""
from pathlib import Path
import hashlib,json,os,plistlib,shutil,subprocess,tempfile,uuid,tarfile

OLD_ID='com.tencent.xinWeChat'
NEW_ID='com.wemac.auto.client'
CORE_SHA='8180e3d032ca7e5e5136a17d117370143aae562686d37eec26af8215b3970cc2'
MAGICS={b'\xcf\xfa\xed\xfe',b'\xce\xfa\xed\xfe',b'\xca\xfe\xba\xbe',b'\xca\xfe\xba\xbf'}

def run(args):
    result=subprocess.run([str(x) for x in args],capture_output=True,text=True)
    if result.returncode:raise RuntimeError(f'{Path(str(args[0])).name} 失败：'+result.stderr[-1200:])
    return result

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def remap(v):
    if isinstance(v,str):return v.replace(OLD_ID,NEW_ID)
    if isinstance(v,list):return [remap(x) for x in v]
    if isinstance(v,dict):return {remap(k):remap(x) for k,x in v.items()}
    return v

def validate_source(source):
    source=Path(source).resolve()
    info=plistlib.loads((source/'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier')!=OLD_ID or str(info.get('CFBundleVersion'))!='270348':
        raise ValueError('需要原版微信 4.2.0（270348），此版本的内部函数才经过验证。')
    if digest(source/'Contents/Resources/wechat.dylib')!=CORE_SHA:
        raise ValueError('微信核心文件与受支持版本不匹配。')
    run(['/usr/bin/codesign','--verify','--deep','--strict',source])
    return source

def signing_plan(source):
    import re
    nodes={source}
    for p in source.rglob('*'):
        if p.is_symlink():continue
        if p.is_dir() and p.suffix in ('.app','.framework','.xpc','.bundle'):
            if subprocess.run(['/usr/bin/codesign','-dv',str(p)],capture_output=True).returncode==0:nodes.add(p)
        elif p.is_file():
            with p.open('rb') as f:magic=f.read(4)
            if magic in MAGICS:nodes.add(p)
    managed=set()
    for p in nodes:
        if p.is_dir():
            for infofile in [p/'Contents/Info.plist',p/'Resources/Info.plist']:
                if infofile.exists():
                    info=plistlib.loads(infofile.read_bytes());name=info.get('CFBundleExecutable')
                    if name:managed.add((p/('' if p.suffix=='.framework' else 'Contents/MacOS')/name).resolve())
                    break
    result=[]
    for p in sorted(nodes,key=lambda x:(-len(x.parts),str(x))):
        if p.is_file() and p.resolve() in managed:continue
        data=run(['/usr/bin/codesign','-dv',p]).stderr
        identity=re.search(r'^Identifier=(.*)$',data,re.M)
        if not identity:raise ValueError('无法读取组件签名：'+str(p.name))
        raw=run(['/usr/bin/codesign','-d','--entitlements',':-',p]).stdout
        ent=remap(plistlib.loads(raw.encode()) if raw.strip() else {})
        if p==source:ent.update({'com.apple.security.get-task-allow':True,'com.apple.security.cs.disable-library-validation':True})
        result.append((p.relative_to(source),remap(identity[1]),ent))
    return result

def install(source,destination,assistant,payload,data_dir,progress=lambda n,s:None):
    """Only a new destination and absent configuration are accepted; rollback our files."""
    destination=Path(destination).expanduser().resolve();source=validate_source(source)
    assistant=Path(assistant).resolve();payload=Path(payload).resolve();data_dir=Path(data_dir).resolve()
    if destination.exists():raise ValueError('安装目录已存在，请选择一个新的 Wemac-auto 目录；不会覆盖现有安装。')
    if destination==source or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('安装目录不能包含或位于原版微信内。')
    if data_dir.exists() and any(data_dir.iterdir()):raise ValueError('已有 Wemac 配置，请先使用现有安装；安装器不会覆盖账号或配置。')
    for container in [Path.home()/'Library/Containers'/NEW_ID,Path.home()/'Library/Group Containers'/('5A4RE8SF68.'+NEW_ID)]:
        if container.exists():raise ValueError('检测到已有独立微信数据，安装已停止以保留现有账号。')
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=destination.parent/('.wemac-stage-'+uuid.uuid4().hex);stage.mkdir()
    committed=False;created_data=False
    try:
        progress(5,'验证微信与安装资源')
        plan=signing_plan(source)
        progress(12,'复制微信到独立目录（不复制账号数据）')
        target=stage/'WeChat-Wemac.app';run(['/usr/bin/ditto',source,target])
        progress(30,'建立独立账号身份')
        for p in target.rglob('*'):
            if p.is_symlink() or not p.is_file():continue
            if p.suffix=='.plist':
                try:info=plistlib.loads(p.read_bytes())
                except plistlib.InvalidFileException:continue
                new=remap(info)
                if p==target/'Contents/Info.plist':
                    new.update(CFBundleName='Wemac',CFBundleDisplayName='WeChat-Wemac',CFBundleURLTypes=[{'CFBundleURLName':NEW_ID,'CFBundleURLSchemes':['wemac-auto']}])
                if new!=info:p.write_bytes(plistlib.dumps(new))
            else:
                with p.open('rb') as f:magic=f.read(4)
                if magic in MAGICS:
                    raw=p.read_bytes()
                    if OLD_ID.encode() in raw:p.write_bytes(raw.replace(OLD_ID.encode(),NEW_ID.encode()))
        helper=target/'Contents/Frameworks/libaumac_completion.dylib';shutil.copy2(payload/helper.name,helper)
        run(['/usr/bin/codesign','--force','--sign','-','--timestamp=none',helper])
        with tempfile.TemporaryDirectory(prefix='wemac-entitlements-') as td:
            for index,(relative,identity,ent) in enumerate(plan):
                progress(35+int(35*index/max(1,len(plan))),f'逐组件重签名 {index+1}/{len(plan)}')
                args=['/usr/bin/codesign','--force','--sign','-','--timestamp=none','--options','0','--identifier',identity]
                if ent:
                    p=Path(td)/f'{index}.plist';p.write_bytes(plistlib.dumps(ent));args+=['--entitlements',p]
                run(args+[target/relative])
        progress(72,'校验副本与原版签名')
        run(['/usr/bin/codesign','--verify','--deep','--strict',target]);validate_source(source)
        progress(78,'安装机器人、SDK 和原生依赖')
        installed_app=stage/'Wemac-auto.app'
        run(['/usr/bin/ditto',assistant,installed_app])
        infofile=installed_app/'Contents/Info.plist'
        info=plistlib.loads(infofile.read_bytes())
        info.update(CFBundleIdentifier='com.wemac.auto.arona',CFBundleName='Wemac-auto',CFBundleDisplayName='Wemac-auto')
        infofile.write_bytes(plistlib.dumps(info))
        run(['/usr/bin/codesign','--force','--deep','--sign','-','--timestamp=none',installed_app])
        run(['/usr/bin/codesign','--verify','--deep','--strict',installed_app])
        shutil.copytree(payload/'sdk',stage/'sdk')
        (stage/'bin').mkdir()
        cli=stage/'bin/wechat-aumac'
        cli.write_text('#!/bin/sh\nWEMAC_INSTALL_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"\nexec "$WEMAC_INSTALL_ROOT/Wemac-auto.app/Contents/MacOS/Wemac-auto 安装助手" --sdk-cli "$@"\n')
        cli.chmod(0o755)
        (stage/'lib').mkdir();shutil.copy2(payload/'native-db-gate.dylib',stage/'lib/native-db-gate.dylib')
        shutil.copy2(payload/'libopencore-amrnb.dylib',stage/'lib/libopencore-amrnb.dylib')
        profile=json.loads((payload/'native-profile.json').read_text())
        profile.update(app=str(destination/target.name),corePath=str(destination/target.name/'Contents/Resources/wechat.dylib'),sha256=digest(target/'Contents/Resources/wechat.dylib'))
        profile['completionHelper']={'path':str(destination/target.name/'Contents/Frameworks'/helper.name),'sha256':digest(helper)}
        profile['nativeDatabase']['bridge']={'path':str(destination/'lib/native-db-gate.dylib'),'sha256':digest(stage/'lib/native-db-gate.dylib')}
        codec=profile['nativeResources']['wxgfCodec'];codec_name=Path(codec['path']).name
        candidates=list(target.rglob(codec_name))
        if len(candidates)!=1:raise ValueError('未找到唯一的微信图片解码库。')
        codec['path']=str(destination/target.name/candidates[0].relative_to(target));codec['sha256']=digest(candidates[0])
        data_dir.mkdir(parents=True,exist_ok=True);created_data=True
        (data_dir/'native-profile-isolated.json').write_text(json.dumps(profile,indent=2)+'\n')
        (data_dir/'lib').mkdir();shutil.copy2(stage/'lib/libopencore-amrnb.dylib',data_dir/'lib/libopencore-amrnb.dylib')
        archive=payload/'character-voice.tar.gz'
        if archive.is_file():
            online=(payload/'online-models.json').is_file()
            progress(80 if online else 86,'安装角色语音运行环境（不含私人录音）')
            manifest=json.loads((payload/'character-voice.json').read_text())
            extracted=0;total=max(1,manifest['uncompressed_bytes']);last_percent=-1
            with tarfile.open(archive) as resources:
                for member in resources:
                    resources.extract(member,data_dir/'character_voice',filter='data')
                    extracted+=member.size
                    percent=min(100,int(100*extracted/total))
                    if percent!=last_percent:
                        last_percent=percent
                        progress((80+min(8,percent*8//100)) if online else (86+min(10,percent//10)),f'解压语音运行环境 {percent}%')
            # No venv prefix or system Python is needed by the portable runtime.
            run([data_dir/'character_voice/runtime/bin/python3','-c',
                 'import torch,numpy,soundfile,transformers; print("voice runtime ready")'])
            if online:
                from online_models import install_models
                install_models(data_dir/'character_voice',payload/'online-models.json',progress)
        (stage/'installation.json').write_text(json.dumps({'version':'0.3.0','bundle_id':NEW_ID,'account_data_copied':False},indent=2))
        stage.rename(destination);committed=True
        sdk_only=(payload/'product.json').is_file() and json.loads((payload/'product.json').read_text()).get('product')=='sdk'
        progress(100,'SDK 安装完成。请登录独立微信并使用命令行入口。' if sdk_only else '安装完成。首次运行请登录独立微信并配置模型 API。')
        return destination/'Wemac-auto.app'
    except BaseException:
        if created_data:shutil.rmtree(data_dir)
        raise
    finally:
        if not committed:shutil.rmtree(stage,ignore_errors=True)
