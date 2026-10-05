"""Install the private prototype and copy a user-supplied ROM to app-private storage."""
from pathlib import Path
import argparse, hashlib, json, subprocess, tempfile
p=argparse.ArgumentParser();p.add_argument('--device',required=True);p.add_argument('--host',required=True);p.add_argument('--rom',type=Path,required=True);p.add_argument('--skip-install',action='store_true');a=p.parse_args()
root=Path(__file__).resolve().parents[1]
config=json.loads((Path(tempfile.gettempdir())/'shvc-android-tools/tools.json').read_text(encoding='utf-8-sig'))
adb=[str(Path(config['sdk'])/'platform-tools/adb.exe'),'-s',a.device]
def run(*args,**kwargs):return subprocess.run([*adb,*args],check=True,**kwargs)
if not a.skip_install: run('install','-r',str(root/'artifacts/shvc-sfc-live-debug.apk'))
data=a.rom.read_bytes()
staging='/data/local/tmp/shvc-test-game.sfc'
try:
 run('push',str(a.rom),staging)
 run('shell','run-as','com.shvc.sfclive','mkdir','-p','files')
 run('shell','run-as','com.shvc.sfclive','cp',staging,'files/game.sfc')
 digest=run('shell','run-as','com.shvc.sfclive','sha256sum','files/game.sfc',capture_output=True,text=True).stdout.split()[0]
 assert digest==hashlib.sha256(data).hexdigest(), 'ROM copy mismatch'
finally: run('shell','rm','-f',staging)
print('ROM copy verified:',len(data),'bytes',flush=True)
run('shell','am','start','-n','com.shvc.sfclive/.MainActivity','--es','shvc_host',a.host,'--ez','auto_start','true')
