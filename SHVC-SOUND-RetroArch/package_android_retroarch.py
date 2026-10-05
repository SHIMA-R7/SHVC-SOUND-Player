"""Private test packaging of an official RetroArch APK with the SHVC core.
Keeps the official UI/code. Enables debugging for ADB provisioning; uses a local
debug signature, so this APK must not be mistaken for an official release.
"""
from pathlib import Path
import json,struct,subprocess,tempfile,zipfile
ROOT=Path(__file__).resolve().parents[1]
base=Path(tempfile.gettempdir())/'shvc-android-tools'
config=json.loads((base/'tools.json').read_text(encoding='utf-8-sig'))
src=base/'RetroArch_aarch64.apk'
def debuggable(xml):
 data=bytearray(xml);pos=8;renamed=None;resourceMap=None
 while pos<len(data):
  kind,header,size=struct.unpack_from('<HHI',data,pos)
  if kind==1:
   count,styles,flags,start=struct.unpack_from('<IIII',data,pos+8)
   assert not (flags&0x100), 'Expected UTF-16 manifest string pool'
   for i in range(count):
    offset=struct.unpack_from('<I',data,pos+header+i*4)[0]
    at=pos+start+offset;length=struct.unpack_from('<H',data,at)[0]
    value=data[at+2:at+2+length*2].decode('utf-16le')
    if value=='allowBackup':
     new='debuggable'.encode('utf-16le');assert len(new)<=length*2
     struct.pack_into('<H',data,at,len(new)//2)
     data[at+2:at+2+length*2+2]=new+b'\0'*(length*2+2-len(new));renamed=i
  elif kind==0x180:resourceMap=(pos,header,size)
  pos+=size
 assert renamed is not None and resourceMap is not None
 pos,header,size=resourceMap;assert header+renamed*4+4<=size
 assert struct.unpack_from('<I',data,pos+header+renamed*4)[0]==0x01010280
 struct.pack_into('<I',data,pos+header+renamed*4,0x0101000f)
 return bytes(data)
unsigned=base/'retroarch-shvc-unsigned.apk'
core=ROOT/'SHVC-SOUND-Android-SFC/app/src/main/jniLibs/arm64-v8a'
with zipfile.ZipFile(src) as source,zipfile.ZipFile(unsigned,'w',zipfile.ZIP_DEFLATED) as target:
 for item in source.infolist():
  if item.filename.upper().startswith('META-INF/'):continue
  if item.filename in ('lib/arm64-v8a/libc++_shared.so','lib/arm64-v8a/snes9x_shvc_libretro_android.so'):continue
  payload=source.read(item.filename)
  if item.filename=='AndroidManifest.xml':payload=debuggable(payload)
  target.writestr(item,payload)
 target.write(core/'libshvc_core.so','lib/arm64-v8a/snes9x_shvc_libretro_android.so')
 target.write(core/'libc++_shared.so','lib/arm64-v8a/libc++_shared.so')
build=Path(config['sdk'])/'build-tools/36.0.0'
aligned=base/'retroarch-shvc-aligned.apk'
subprocess.run([str(build/'zipalign.exe'),'-f','-p','4',str(unsigned),str(aligned)],check=True)
key=base/'shvc-private-debug.keystore'
if not key.exists():
 subprocess.run([str(Path(config['java'])/'bin/keytool.exe'),'-genkeypair','-keystore',str(key),'-storepass','android','-keypass','android','-alias','androiddebugkey','-keyalg','RSA','-keysize','2048','-validity','10000','-dname','CN=SHVC Private Debug'],check=True)
out=ROOT/'SHVC-SOUND-RetroArch/artifacts/retroarch-shvc-aarch64-debug.apk'
env=__import__('os').environ.copy();env['JAVA_HOME']=config['java']
subprocess.run([str(build/'apksigner.bat'),'sign','--ks',str(key),'--ks-pass','pass:android','--key-pass','pass:android','--out',str(out),str(aligned)],env=env,check=True)
subprocess.run([str(build/'apksigner.bat'),'verify',str(out)],env=env,check=True)
print(out)
