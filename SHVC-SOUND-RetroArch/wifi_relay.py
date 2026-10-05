"""LAN TCP -> local real-APU named pipe; USB is not used for game data."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import socket
import time
from pathlib import Path
CACHE=Path(__file__).resolve().parents[1]/"docs/tmp/wifi-bridge-ip.txt"
from ble_relay import kernel,connect_pipe,read_packet,write_packet

def discover():
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as udp:
        udp.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1); udp.settimeout(2)
        for _ in range(5):
            udp.sendto(b'SHVC-APU-FIND1',('255.255.255.255',28955))
            try:
                reply,address=udp.recvfrom(64)
                if reply==b'SHVC-APU-WIFI1': return address[0]
            except socket.timeout: pass
    raise RuntimeError('Wi-Fi bridge not found; pass --host with its LAN address')

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--host'); args=parser.parse_args()
    address=args.host or (CACHE.read_text(encoding='utf-8').strip() if CACHE.exists() else discover())
    try:
        connection=socket.create_connection((address,28954),timeout=3)
    except OSError:
        if args.host: raise
        address=discover(); connection=socket.create_connection((address,28954),timeout=3)
    with connection as link:
        CACHE.parent.mkdir(parents=True,exist_ok=True); CACHE.write_text(address,encoding='utf-8')
        link.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        def receive(count):
            result=bytearray()
            while len(result)<count:
                data=link.recv(count-len(result))
                if not data: raise ConnectionError('ESP disconnected')
                result.extend(data)
            return bytes(result)
        print(f'Wi-Fi connected {address}:28954',flush=True)
        handle=kernel.CreateNamedPipeW(r'\\.\pipe\shvc-apu-ble',3,0,1,8192,8192,0,None)
        if handle==W.HANDLE(-1).value: raise C.WinError(C.get_last_error())
        try:
            while True:
                print('READY: launch core with SHVC_APU_PORT=BLE (Wi-Fi relay)',flush=True)
                connect_pipe(handle); packets=0; timings=[]
                try:
                    while True:
                        request=read_packet(handle); started=time.perf_counter()
                        link.sendall(request); header=receive(8)
                        count=int.from_bytes(header[6:8],'little')
                        if header[0]!=0xac or count>512: raise RuntimeError('Bad Wi-Fi reply')
                        write_packet(handle,header+receive(count+2))
                        timings.append((time.perf_counter()-started)*1000); packets+=1
                        if packets%300==0:
                            print(f'packets={packets} average roundtrip={sum(timings)/len(timings):.2f}ms max={max(timings):.2f}ms',flush=True); timings.clear()
                except EOFError:
                    print('Core disconnected',flush=True)
                finally:
                    kernel.DisconnectNamedPipe(handle)
        finally:
            kernel.CloseHandle(handle)

if __name__=='__main__': main()
