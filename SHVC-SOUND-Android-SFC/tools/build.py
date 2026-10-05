"""Private Android prototype build. No ROMs or Wi-Fi credentials are packaged."""
from pathlib import Path
import json, os, shutil, subprocess, tempfile
root=Path(__file__).resolve().parents[1]
repo=root.parent
tools=Path(tempfile.gettempdir())/'shvc-android-tools'
config=json.loads((tools/'tools.json').read_text(encoding='utf-8-sig'))
ndk=Path(config['sdk'])/'ndk/27.2.12479018/toolchains/llvm/prebuilt/windows-x86_64'
jni=root/'app/src/main/jniLibs/arm64-v8a'
assert (jni/'libshvc_core.so').exists(), 'Build build_android_core.py first'
subprocess.run([str(ndk/'bin/clang++.exe'),'--target=aarch64-linux-android26','-std=c++17','-O2','-fPIC','-shared','-nostdlib++','-lc++_shared','-Wl,--no-undefined','-Wl,-z,max-page-size=16384',str(root/'native/frontend.cpp'),'-I'+str(repo/'docs/tmp/snes9x-hardware-source/libretro'),'-L'+str(jni),'-lshvc_core','-landroid','-llog','-o',str(jni/'libshvc_frontend.so')],check=True)
work=tools/'sfc-workspace'
shutil.copytree(root,work,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.gradle','build','artifacts','__pycache__'))
(work/'local.properties').write_text('sdk.dir='+config['sdk'].replace('\\','/').replace(':','\\:')+'\n',encoding='utf-8')
env=os.environ.copy();env['JAVA_HOME']=config['java'];env['ANDROID_HOME']=config['sdk'];env['GRADLE_USER_HOME']=str(Path(tempfile.gettempdir())/'shvc-gradle-cache')
subprocess.run([config['gradle'],'--no-daemon','--console=plain',':app:assembleDebug',':app:lintDebug'],cwd=work,env=env,check=True)
out=root/'artifacts';out.mkdir(exist_ok=True)
shutil.copy2(work/'app/build/outputs/apk/debug/app-debug.apk',out/'shvc-sfc-live-debug.apk')
print(out/'shvc-sfc-live-debug.apk')
