"""Build an experimental private Snes9x core with a real APU port backend.
The upstream tree stays in ignored docs/tmp; no ROM data is copied.
"""
from pathlib import Path
import re, shutil, subprocess, tempfile, concurrent.futures, json, argparse, ipaddress
parser=argparse.ArgumentParser();parser.add_argument('--host');args=parser.parse_args()
if args.host: args.host=str(ipaddress.IPv4Address(args.host))
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'docs/tmp/snes9x-hardware-source'
work=Path(tempfile.gettempdir())/'shvc-snes9x-android-core'
shutil.copytree(source,work,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','*.o'))
shutil.copy2(ROOT/'SHVC-SOUND-RetroArch/shvc_apu_bridge.h',work/'apu/shvc_apu_bridge.h')
shutil.copy2(ROOT/'SHVC-SOUND-RetroArch/shvc_android_transport.h',work/'apu/shvc_android_transport.h')
p=work/'apu/apu.cpp'; s=p.read_text(encoding='utf-8')
s=s.replace('#include "apu.h"','#include "apu.h"\n#include "shvc_apu_bridge.h"')
s=s.replace('return ((uint8)SNES::smp.port_read(port & 3));', 'bool wasBoot=shvc::boot; uint8 value=shvc::read(port, (uint8)SNES::smp.port_read(port & 3), SNES::smp.regs.pc >= 0xffc0 && SNES::smp.status.iplrom_enable, SNES::smp.regs.pc); if(wasBoot && !shvc::boot) { SNES::smp.clock -= 20480; SNES::smp.enter(); } if(shvc::readyForIpl && !shvc::boot) { for(unsigned i=0;i<1000 && (SNES::smp.port_read(0)!=0xaa || SNES::smp.port_read(1)!=0xbb);i++) { for(unsigned p=0;p<4;p++) SNES::cpu.port_write(p,shvc::last[p]); SNES::smp.clock-=1024; SNES::smp.enter(); } } return value;')
s=s.replace('SNES::cpu.port_write(port & 3, byte);','SNES::cpu.port_write(port & 3, byte);\n    shvc::write(port, byte);')
s=s.replace('void S9xResetAPU(void)\n{','void S9xResetAPU(void)\n{\n    shvc::reset();')
s=s.replace('void S9xAPUEndScanline(void)\n{','void S9xAPUEndScanline(void)\n{')
s=s.replace('void S9xDeinitAPU(void)\n{','void S9xDeinitAPU(void)\n{\n    shvc::close();')
# Suppress PCM even after a hardware transport failure. Always drain the DSP buffer.
needle='    *sample_count = count;'
assert needle in s
s=s.replace(needle, '    shvc::recordFrame();\n    const char *hardware_port = getenv("SHVC_APU_PORT");\n    *sample_count = (hardware_port && *hardware_port) ? 0 : count;')
s+='\nextern "C" __attribute__((visibility("default"))) unsigned shvc_debug(unsigned which) { switch(which) { case 0:return Registers.PBPC; case 1:return SNES::smp.regs.pc; case 2:return SNES::cpu.port_read(0)|(SNES::cpu.port_read(1)<<8); case 3:return SNES::smp.port_read(0)|(SNES::smp.port_read(1)<<8); case 4:return shvc::writes; case 5:return shvc::packets; case 7:return shvc::failed || shvc::serial==INVALID_HANDLE_VALUE; default:return shvc::boot; } }\n'
p.write_text(s,encoding='utf-8')
# Supply the endpoint through libretro options, without frontend environment hacks.
options=work/'libretro/libretro_core_options.h'
option=('{ "shvc_wifi_address", "SHVC-SOUND: ESP address (Reload Core)", NULL, '
        '"Wi-Fi endpoint. File reads the first IPv4 address from system/shvc-wifi.txt.", NULL, NULL, {'
        '{"file", "From system/shvc-wifi.txt"},'
        +(('{"'+args.host+'", "'+args.host+'"},') if args.host else '')
        +'{NULL, NULL}}, "'+(args.host or 'file')+'" },\n')
options.write_text(options.read_text(encoding='utf-8').replace('struct retro_core_option_v2_definition option_defs_us[] = {','struct retro_core_option_v2_definition option_defs_us[] = {\n'+option),encoding='utf-8')
frontend=work/'libretro/libretro.cpp'
t=frontend.read_text(encoding='utf-8')
t=t.replace('info->library_name = "Snes9x";', 'info->library_name = "Snes9x SHVC WiFi";')
setup='''
    struct retro_variable endpoint = {"shvc_wifi_address", NULL};
    const char *host = getenv("SHVC_APU_PORT");
    char fileHost[64] = {};
    if (environ_cb(RETRO_ENVIRONMENT_GET_VARIABLE, &endpoint) && endpoint.value) {
        host = endpoint.value;
        if (!strcmp(host, "file")) {
            char path[4096]; snprintf(path,sizeof(path),"%s/shvc-wifi.txt",retro_system_directory);
            FILE *file=fopen(path,"r");
            if(file) { if(fscanf(file,"%63s",fileHost)!=1)fileHost[0]=0; fclose(file); }
            host=fileHost;
        }
    }
    if (!host || !*host) host="0.0.0.0";
    setenv("SHVC_APU_PORT",host,1);
    const char *logDir=NULL;
    if(environ_cb(RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY,&logDir) && logDir) {
        char path[4096];snprintf(path,sizeof(path),"%s/shvc-apu.log",logDir);setenv("SHVC_APU_LOG",path,1);
    }
'''
t=t.replace('    // State that SNES9X supports achievements.',setup+'\n    // State that SNES9X supports achievements.')
frontend.write_text(t,encoding='utf-8')
# Parse the explicit upstream source lists, preserving C/C++ compilation.
text=(work/'libretro/Makefile.common').read_text()
files=re.findall(r'\$\((CORE_DIR|LIBRETRO_COMM_DIR)\)/([\w/]+\.(?:cpp|c))',text)
ndk=Path(tempfile.gettempdir())/'shvc-android-tools/sdk/ndk/27.2.12479018/toolchains/llvm/prebuilt/windows-x86_64'
compiler=ndk/'bin/clang++.exe'
target=['--target=aarch64-linux-android26']
includes=[work/'libretro',work/'libretro/libretro-common/include',work,work/'apu',work/'apu/bapu']
flags=[*target,'-fPIC','-O2','-fno-strict-aliasing','-D__LIBRETRO__','-DALLOW_CPU_OVERCLOCK','-DNDEBUG','-Wno-deprecated-declarations']+[f'-I{p}' for p in includes]
objects=[]
def compile_file(entry):
 var,rel=entry; p=(work if var=='CORE_DIR' else work/'libretro/libretro-common')/rel
 obj=work/('obj/'+var+'_'+rel.replace('/','_')+'.o'); obj.parent.mkdir(exist_ok=True)
 extra=['-std=c++14','-fno-exceptions','-fno-rtti'] if p.suffix=='.cpp' else []
 if p.suffix=='.cpp' and obj.exists() and obj.stat().st_mtime>p.stat().st_mtime: return obj
 driver=compiler if extra else ndk/'bin/clang.exe'
 result=subprocess.run([str(driver),*flags,*extra,'-c',str(p),'-o',str(obj)],capture_output=True,text=True,encoding='utf-8',errors='replace')
 if result.returncode: raise RuntimeError(str(p)+'\n'+result.stderr[-5000:])
 print('compiled',rel,flush=True); return obj
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 objects=list(pool.map(compile_file,dict.fromkeys(files)))
out=ROOT/'SHVC-SOUND-Android-SFC/app/src/main/jniLibs/arm64-v8a/libshvc_core.so'; out.parent.mkdir(parents=True,exist_ok=True)
with (out.parent/'link.log').open('w',encoding='utf-8') as log:
 subprocess.run([str(compiler),*target,'-shared','-nostdlib++','-lc++_shared','-Wl,--no-undefined','-Wl,-z,max-page-size=16384',*[str(p) for p in objects],'-o',str(out)],check=True,stdout=log,stderr=log)
shutil.copy2(ndk/'sysroot/usr/lib/aarch64-linux-android/libc++_shared.so',out.parent/'libc++_shared.so')
(out.parent/'source-version.txt').write_text(subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True),encoding='utf-8')
print(out)
