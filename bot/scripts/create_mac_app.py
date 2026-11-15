"""Build a local app launcher and create the requested desktop shortcut."""
from __future__ import annotations
import json,os,plistlib,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SDK=ROOT.parent
folder=ROOT/'.runtime';app=folder/'什亭之匣.app';resources=app/'Contents/Resources';macos=app/'Contents/MacOS'
resources.mkdir(parents=True,exist_ok=True);macos.mkdir(parents=True,exist_ok=True)
iconset=folder/'Arona.iconset';iconset.mkdir(parents=True,exist_ok=True)
from PIL import Image
with Image.open(ROOT/'assets/app_icon.png') as icon:
    for size in (16,32,128,256,512):
        icon.resize((size,size),Image.Resampling.LANCZOS).save(iconset/f'icon_{size}x{size}.png')
        icon.resize((size*2,size*2),Image.Resampling.LANCZOS).save(iconset/f'icon_{size}x{size}@2x.png')
subprocess.run(['iconutil','-c','icns',str(iconset),'-o',str(resources/'Arona.icns')],check=True)
info={'CFBundleIdentifier':'com.wemac.auto.arona','CFBundleName':'什亭之匣','CFBundleDisplayName':'什亭之匣',
      'CFBundleExecutable':'Arona','CFBundleIconFile':'Arona.icns','CFBundlePackageType':'APPL',
      'CFBundleShortVersionString':'1.3.1','CFBundleVersion':'13101','NSHighResolutionCapable':True,
      'LSMinimumSystemVersion':'12.0','LSMultipleInstancesProhibited':True,
      'LSArchitecturePriority':['arm64'],'LSRequiresNativeExecution':True}
with (app/'Contents/Info.plist').open('wb') as stream:plistlib.dump(info,stream)
python=SDK/'.venv-bot/bin/python';launcher=macos/'Arona'
log=Path.home()/'Library/Application Support/WemacAuto/Arona/logs/launcher.log';log.parent.mkdir(parents=True,exist_ok=True)
source=folder/'AronaLauncher.c'
source.write_text('''#include <unistd.h>
#include <stdlib.h>
#include <fcntl.h>
#include <stdio.h>
int main(void) {
    setenv("PYTHONPATH", %s, 1);
    setenv("PYTHONUNBUFFERED", "1", 1);
    int logfd=open(%s, O_WRONLY|O_CREAT|O_APPEND, 0600);
    if(logfd>=0){dup2(logfd,1);dup2(logfd,2);close(logfd);}
    char *args[]={%s,%s,NULL};
    execv(args[0],args);
    perror("Cannot start Arona Python runtime");
    return 1;
}
''' % (json.dumps(str(SDK/'src')+':'+str(ROOT)),json.dumps(str(log)),
       json.dumps(str(python)),json.dumps(str(ROOT/'run.py'))))
subprocess.run(['clang','-arch','arm64','-Os',str(source),'-o',str(launcher)],check=True,capture_output=True)
subprocess.run(['codesign','--force','--sign','-','--timestamp=none',str(app)],check=True,capture_output=True)
desktop=Path.home()/'Desktop/什亭之匣.app'
if desktop.exists() or desktop.is_symlink():
    if desktop.is_symlink() and desktop.resolve()==app.resolve():desktop.unlink()
    else:raise RuntimeError('Desktop item already exists; leaving it intact: '+str(desktop))
desktop.symlink_to(app,target_is_directory=True)
print('APP',app);print('DESKTOP SHORTCUT',desktop)
