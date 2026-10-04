"""Download verified official Android/JDK/Gradle tools into a private temp directory."""
from pathlib import Path
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

BASE=Path(tempfile.gettempdir())/'shvc-android-tools'
BASE.mkdir(parents=True,exist_ok=True)
def get(url):
    return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'SHVC-SOUND-build'}),timeout=120)
def download(name,url,digest=None,algorithm='sha256'):
    dest=BASE/name
    if not dest.exists():
        print('DOWNLOAD',name,flush=True)
        with get(url) as src,dest.with_suffix('.part').open('wb') as out: shutil.copyfileobj(src,out)
        dest.with_suffix('.part').replace(dest)
    if digest:
        h=hashlib.new(algorithm)
        with dest.open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
        if h.hexdigest().lower()!=digest.lower(): raise RuntimeError('Checksum mismatch: '+name)
    print('VERIFIED',name,flush=True)
    return dest
def extract(archive,target):
    target.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            if not (target/item.filename).resolve().is_relative_to(target.resolve()): raise RuntimeError('Unsafe archive path')
        z.extractall(target)
def child(node,name): return next((n for n in node if n.tag.split('}')[-1]==name),None)

assets=json.load(get('https://api.adoptium.net/v3/assets/latest/17/hotspot?architecture=x64&image_type=jdk&os=windows&vendor=eclipse'))
jdk=assets[0]['binary']['package']
repo=ET.fromstring(get('https://dl.google.com/android/repository/repository2-3.xml').read())
candidates=[]
for package in repo:
    if not package.get('path','').startswith('cmdline-tools;'): continue
    channel=child(package,'channelRef')
    if channel is not None and channel.get('ref')!='channel-0': continue
    revision=child(package,'revision')
    version=tuple(int(child(revision,k).text) if child(revision,k) is not None else 0 for k in ['major','minor','micro'])
    archives=child(package,'archives')
    if archives is None: continue
    for archive in archives:
        host=child(archive,'host-os'); complete=child(archive,'complete')
        if host is not None and host.text=='windows' and complete is not None:
            checksum=child(complete,'checksum')
            candidates.append((version,child(complete,'url').text,checksum.text,checksum.get('type','sha1')))
_,cturl,cthash,ctalgo=max(c for c in candidates if c[0][0]==19)
gradle_hash=get('https://services.gradle.org/distributions/gradle-8.13-bin.zip.sha256').read().decode().strip()
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    futures=[pool.submit(download,'jdk17.zip',jdk['link'],jdk['checksum']),
             pool.submit(download,'gradle.zip','https://services.gradle.org/distributions/gradle-8.13-bin.zip',gradle_hash),
             pool.submit(download,'cmdline19.zip','https://dl.google.com/android/repository/'+cturl,cthash,ctalgo),
             pool.submit(download,'platform-tools.zip','https://dl.google.com/android/repository/platform-tools-latest-windows.zip')]
    archives=[f.result() for f in futures]
if not (BASE/'jdk').exists(): extract(archives[0],BASE/'jdk')
if not (BASE/'gradle-8.13').exists(): extract(archives[1],BASE)
sdk=BASE/'sdk'
if not (sdk/'cmdline-tools/19.0/bin/sdkmanager.bat').exists():
    extract(archives[2],BASE/'cmdline19-extracted')
    shutil.copytree(BASE/'cmdline19-extracted/cmdline-tools',sdk/'cmdline-tools/19.0',dirs_exist_ok=True)
if not (sdk/'platform-tools/adb.exe').exists(): extract(archives[3],sdk)
java=next((BASE/'jdk').glob('*/bin/java.exe')).parent.parent
config={'java':str(java),'sdk':str(sdk),'gradle':str(BASE/'gradle-8.13/bin/gradle.bat')}
(BASE/'tools.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
print('TOOLS',json.dumps(config),flush=True)
env=os.environ.copy(); env['JAVA_HOME']=str(java); env['PATH']=str(java/'bin')+os.pathsep+env['PATH']
manager=str(sdk/'cmdline-tools/19.0/bin/sdkmanager.bat')
subprocess.run([manager,'--sdk_root='+str(sdk),'--licenses'],input='y\n'*80,text=True,env=env,check=True)
subprocess.run([manager,'--sdk_root='+str(sdk),'platforms;android-36','build-tools;36.0.0'],env=env,check=True)
subprocess.run([str(sdk/'platform-tools/adb.exe'),'devices','-l'],check=True)
