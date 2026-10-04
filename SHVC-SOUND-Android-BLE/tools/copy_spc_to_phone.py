"""Copy SPC files only, preserving document subfolders; verify every SHA-256."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

p=argparse.ArgumentParser()
p.add_argument('--adb',required=True)
p.add_argument('--serial',help='Target ADB device serial (recommended with multiple phones)')
p.add_argument('--staging',type=Path,required=True)
p.add_argument('--root',type=Path,action='append',required=True)
p.add_argument('--phone-root',default='/sdcard/Download/SHVC-SPC')
a=p.parse_args()
adb=[a.adb]+(['-s',a.serial] if a.serial else [])
assert a.phone_root.startswith('/sdcard/Download/') and '..' not in a.phone_root
a.staging.mkdir(parents=True,exist_ok=True)
expected={}; seen=set(); total=0
for index,root in enumerate(a.root):
    found=subprocess.run(['rg','--files','--hidden','-g','*.spc','-g','*.SPC','-g','!.git',str(root)],capture_output=True,encoding='utf-8')
    if found.returncode not in (0,1): raise RuntimeError(found.stderr)
    for name in found.stdout.splitlines():
        source=Path(name)
        identity=str(source.resolve()).casefold()
        if identity in seen: continue
        seen.add(identity)
        relative=Path('Documents' if index==0 else f'Documents-{index+1}')/source.relative_to(root)
        target=a.staging/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)
        expected[a.phone_root+'/'+relative.as_posix()]=hashlib.sha256(source.read_bytes()).hexdigest()
        total+=source.stat().st_size
print(f'Copying {len(expected)} SPC files, {total} bytes',flush=True)
subprocess.run(adb+['shell','mkdir','-p',a.phone_root],check=True)
subprocess.run(adb+['push',str(a.staging)+ '/.',a.phone_root+'/'],check=True)
command='find '+shlex.quote(a.phone_root)+" -type f -iname '*.spc' -exec sha256sum {} \\;"
result=subprocess.run(adb+['shell',command],capture_output=True,encoding='utf-8',check=True)
actual={}
for line in result.stdout.splitlines():
    digest,name=line.split(maxsplit=1)
    actual[name]=digest
bad=[name for name,digest in expected.items() if actual.get(name)!=digest]
if bad: raise RuntimeError(f'{len(bad)} files failed SHA-256 verification')
# ADB/MTP copies can exist as MediaStore.Files rows with is_download=0.
# Refresh only this copied directory so ACTION_OPEN_DOCUMENT/Downloads sees its contents.
canonical=a.phone_root.replace('/sdcard/','/storage/emulated/0/',1)
scan='content call --uri content://media --method scan_file --arg '+shlex.quote(canonical)
subprocess.run(adb+['shell',scan],check=True,capture_output=True,encoding='utf-8')
relative=a.phone_root.removeprefix('/sdcard/').rstrip('/')+'/'
selection="relative_path LIKE '"+relative.replace("'","''")+"%'"
query='content query --uri content://media/external/downloads --projection _data --where '+shlex.quote(selection)
indexed=subprocess.run(adb+['shell',query],check=True,capture_output=True,encoding='utf-8')
visible={line.split('_data=',1)[1].replace('/storage/emulated/0/','/sdcard/',1)
         for line in indexed.stdout.splitlines() if '_data=' in line}
missing=[name for name in expected if name not in visible]
if missing: raise RuntimeError(f'{len(missing)} verified SPC files are missing from Android Downloads index')
print(json.dumps({'copied' :len(expected),'verified':len(expected),'bytes':total,'indexed':len(expected),'phoneFolder':a.phone_root}),flush=True)
