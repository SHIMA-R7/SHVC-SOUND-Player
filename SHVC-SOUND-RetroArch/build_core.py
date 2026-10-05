"""Build an experimental private Snes9x core with a real APU port backend.
The upstream tree stays in ignored docs/tmp; no ROM data is copied.
"""
from pathlib import Path
import re, shutil, subprocess, tempfile, concurrent.futures, json
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'docs/tmp/snes9x-hardware-source'
work=Path(tempfile.gettempdir())/'shvc-snes9x-core'
shutil.copytree(source,work,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','*.o'))
shutil.copy2(ROOT/'SHVC-SOUND-RetroArch/shvc_apu_bridge.h',work/'apu/shvc_apu_bridge.h')
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
s+='\nextern "C" __declspec(dllexport) unsigned shvc_debug(unsigned which) { switch(which) { case 0:return Registers.PBPC; case 1:return SNES::smp.regs.pc; case 2:return SNES::cpu.port_read(0)|(SNES::cpu.port_read(1)<<8); case 3:return SNES::smp.port_read(0)|(SNES::smp.port_read(1)<<8); case 4:return shvc::writes; case 5:return shvc::packets; case 7:return shvc::failed || shvc::serial==INVALID_HANDLE_VALUE; default:return shvc::boot; } }\n'
p.write_text(s,encoding='utf-8')
# Parse the explicit upstream source lists, preserving C/C++ compilation.
text=(work/'libretro/Makefile.common').read_text()
files=re.findall(r'\$\((CORE_DIR|LIBRETRO_COMM_DIR)\)/([\w/]+\.(?:cpp|c))',text)
zig=Path('C:/Users/Yugo/pico/zig/zig-x86_64-windows-0.16.0/zig.exe')
includes=[work/'libretro',work/'libretro/libretro-common/include',work,work/'apu',work/'apu/bapu']
flags=['-target','x86_64-windows-gnu','-O2','-fno-strict-aliasing','-D__LIBRETRO__','-DALLOW_CPU_OVERCLOCK','-D__WIN32__','-DNDEBUG','-Wno-deprecated-declarations']+[f'-I{p}' for p in includes]
objects=[]
def compile_file(entry):
 var,rel=entry; p=(work if var=='CORE_DIR' else work/'libretro/libretro-common')/rel
 obj=work/('obj/'+var+'_'+rel.replace('/','_')+'.o'); obj.parent.mkdir(exist_ok=True)
 extra=['-std=c++14','-fno-exceptions','-fno-rtti'] if p.suffix=='.cpp' else []
 if obj.exists() and obj.stat().st_mtime>p.stat().st_mtime: return obj
 result=subprocess.run([str(zig),'c++' if extra else 'cc',*flags,*extra,'-c',str(p),'-o',str(obj)],capture_output=True,text=True,encoding='utf-8',errors='replace')
 if result.returncode: raise RuntimeError(str(p)+'\n'+result.stderr[-5000:])
 print('compiled',rel,flush=True); return obj
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 objects=list(pool.map(compile_file,dict.fromkeys(files)))
out=ROOT/'SHVC-SOUND-RetroArch/artifacts/snes9x_shvc_libretro.dll'; out.parent.mkdir(exist_ok=True)
with (out.parent/'link.log').open('w',encoding='utf-8') as log:
 subprocess.run([str(zig),'c++','-target','x86_64-windows-gnu','-shared',*[str(p) for p in objects],'-o',str(out)],check=True,stdout=log,stderr=log)
(out.parent/'source-version.txt').write_text(subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True),encoding='utf-8')
print(out)
