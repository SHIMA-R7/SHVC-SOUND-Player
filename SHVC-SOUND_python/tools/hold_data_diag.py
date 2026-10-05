"""Hold data via U2, reset/mute asserted, WR/RD HIGH. Use with SHVC removed."""
import argparse
import time
import serial
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('port')
p.add_argument('--value',type=lambda s:int(s,0),default=0)
a=p.parse_args()
s=serial.Serial(a.port,500000,timeout=5)
time.sleep(2)
s.reset_input_buffer()
def hold(value):
    if not 0<=value<=255: raise ValueError('Data must be 0..255')
    s.write(bytes([17,value]))
    response=s.read(4)
    if response!=bytes([17,value,value,value]):
        raise RuntimeError(f'Unexpected data hold response: {response.hex()}')
    print(f'DATA HELD {value:02X}; ESP32 latch/pads confirmed. U2 enabled, U4 disabled, RESET LOW, WR/RD HIGH.',flush=True)
try:
    hold(a.value)
    print('Connection remains open. Commands: low, high, 0xNN, exit.',flush=True)
    while True:
        command=input().strip().lower()
        if command=='exit': break
        if command=='low': hold(0)
        elif command=='high': hold(255)
        else: hold(int(command,0))
finally:
    try:
        # Disable U2 and leave WR HIGH via the existing static control command.
        s.write(bytes([16,1]))
        print('Released data outputs:',s.read(4).hex(),flush=True)
    finally:
        s.close()
