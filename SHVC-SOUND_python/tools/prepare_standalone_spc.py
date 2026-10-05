"""Generate local flash data from a user-supplied SPC. Do not publish spc_data.h."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from spc_play import SpcFile,build_final_stub,handshake_values

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('spc',type=Path)
p.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'esp32_spc_standalone/spc_data.h')
a=p.parse_args()
s=SpcFile(a.spc)
stub=build_final_stub(s,port_handshake=True)
signal,final=handshake_values(s)
def array(name,data):
    lines=[f'static const uint8_t {name}[] PROGMEM = {{']
    for i in range(0,len(data),16): lines.append('  '+','.join(f'0x{v:02X}' for v in data[i:i+16])+',')
    return '\n'.join(lines+['};'])
title=s.tags.get('title') or a.spc.stem
text='// Generated locally from an SPC snapshot; excluded from Git.\n#pragma once\n#include <Arduino.h>\n'
text+=f'static const char SPC_TITLE[] = {json.dumps(title,ensure_ascii=True)};\n'
text+=f'static const char SPC_SHA256[] = "{hashlib.sha256(a.spc.read_bytes()).hexdigest()}";\n'
text+=f'static const uint16_t STUB_ADDRESS = 0x{0xffc0-len(stub):04X};\n'
text+=f'static const uint8_t START_SIGNAL = {signal};\n'
text+=array('FINAL_PORTS',s.ram[0xf4:0xf8])+'\n'
text+=array('SPC_RAM',s.ram)+'\n'+array('RESTORE_STUB',stub)+'\n'
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(text,encoding='utf-8')
print(f'Prepared {title}: RAM={len(s.ram)}, stub={len(stub)}, address=${0xffc0-len(stub):04X}')
print('Local generated data:',a.output)
