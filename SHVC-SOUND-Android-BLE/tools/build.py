"""Build in an ASCII path; copy the debug APK back to artifacts/."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parents[1]
base=Path(tempfile.gettempdir())/'shvc-android-tools'
tools=json.loads((base/'tools.json').read_text(encoding='utf-8'))
work_root=Path(os.environ.get('SHVC_ANDROID_WORK_ROOT',tempfile.gettempdir()))
workspace=work_root/'shvc-android-build'
shutil.copytree(root,workspace,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.gradle','build','artifacts','__pycache__'))
(workspace/'local.properties').write_text('sdk.dir='+tools['sdk'].replace('\\','/').replace(':','\\:')+'\n',encoding='utf-8')
env=os.environ.copy(); env['JAVA_HOME']=tools['java']; env['ANDROID_HOME']=tools['sdk']
env['GRADLE_USER_HOME']=str(work_root/'shvc-gradle-cache'); env['PATH']=str(Path(tools['java'])/'bin')+os.pathsep+env['PATH']
tasks=sys.argv[1:] or [':app:assembleDebug',':app:testDebugUnitTest',':app:lintDebug']
subprocess.run([tools['gradle'],'--no-daemon','--console=plain',*tasks],cwd=workspace,env=env,check=True)
apk=workspace/'app/build/outputs/apk/debug/app-debug.apk'
if apk.exists():
    output=root/'artifacts/shvc-sound-deck-debug.apk'
    output.parent.mkdir(exist_ok=True); shutil.copy2(apk,output)
    print('APK',output,flush=True)
