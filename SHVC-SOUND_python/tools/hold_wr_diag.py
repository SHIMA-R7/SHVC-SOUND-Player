"""Keep serial connection open while holding WR for a multimeter test."""
import argparse
import time
import serial

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('port')
p.add_argument('--level', choices=['low', 'high'], default='low')
a = p.parse_args()
s = serial.Serial(a.port, 500000, timeout=5)
time.sleep(2)
s.reset_input_buffer()
def hold(level):
    s.write(bytes([16, level]))
    response = s.read(4)
    if response != bytes([16, level, level, level]):
        raise RuntimeError(f'Unexpected WR hold response: {response.hex()}')
    print(f'WR HELD {"HIGH" if level else "LOW"}; ESP32 latch and pad confirmed. Reset/mute asserted, buffers disabled.', flush=True)
try:
    hold(int(a.level == 'high'))
    print('Connection remains open. Commands: low, high, exit.', flush=True)
    while True:
        command = input().strip().lower()
        if command == 'exit':
            break
        if command in ('low', 'high'):
            hold(int(command == 'high'))
finally:
    try:
        hold(1)
    finally:
        s.close()
