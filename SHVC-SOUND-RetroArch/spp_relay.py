"""Bluetooth Classic RFCOMM -> same local real-APU named pipe."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import time
import binascii
from ble_relay import kernel,connect_pipe,read_packet,write_packet

class BluetoothAddress(C.Structure):
    _pack_=1
    _fields_=[('family',C.c_ushort),('address',C.c_ulonglong),
              ('service',C.c_ubyte*16),('channel',C.c_ulong)]

ws=C.WinDLL('ws2_32')
ws.socket.argtypes=[C.c_int,C.c_int,C.c_int]; ws.socket.restype=C.c_size_t
ws.connect.argtypes=[C.c_size_t,C.c_void_p,C.c_int]
ws.send.argtypes=[C.c_size_t,C.c_void_p,C.c_int,C.c_int]
ws.recv.argtypes=ws.send.argtypes
ws.closesocket.argtypes=[C.c_size_t]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--address',default='A4:F0:0F:69:0A:EE')
    parser.add_argument('--channel',type=int,default=1)
    args=parser.parse_args()
    timer=C.WinDLL('winmm'); timer.timeBeginPeriod(1)
    startup=C.create_string_buffer(512)
    if ws.WSAStartup(0x202,startup): raise RuntimeError('WSA startup failed')
    sock=ws.socket(32,1,3) # AF_BTH, SOCK_STREAM, BTHPROTO_RFCOMM
    address=BluetoothAddress(32,int(args.address.replace(':',''),16),(C.c_ubyte*16)(),args.channel)
    def receive(count):
        result=bytearray()
        while len(result)<count:
            buffer=C.create_string_buffer(count-len(result))
            got=ws.recv(sock,buffer,len(buffer),0)
            if got<=0: raise EOFError(f'RFCOMM receive error {ws.WSAGetLastError()}')
            result.extend(buffer.raw[:got])
        return bytes(result)
    try:
        if ws.connect(sock,C.byref(address),C.sizeof(address)):
            raise RuntimeError(f'RFCOMM connect error {ws.WSAGetLastError()}')
        print(f'SPP connected {args.address} channel={args.channel}',flush=True)
        handle=kernel.CreateNamedPipeW(r'\\.\pipe\shvc-apu-ble',3,0,1,8192,8192,0,None)
        if handle==W.HANDLE(-1).value: raise C.WinError(C.get_last_error())
        try:
            while True:
                print('READY: launch core with SHVC_APU_PORT=BLE (SPP relay)',flush=True)
                connect_pipe(handle); packets=0; timings=[]
                try:
                    while True:
                        request=read_packet(handle); started=time.perf_counter()
                        # Arduino BluetoothSerial has a 512-byte receive queue.
                        # Execute smaller verified batches without dropping IPL ACKs.
                        payload=request[8:]
                        if binascii.crc_hqx(payload,0xffff)!=int.from_bytes(request[6:8],'little'): raise RuntimeError('Request CRC failure')
                        result=bytearray(); status=0; failed=0xffff
                        for offset in range(0,len(payload),384):
                            body=payload[offset:offset+384]
                            fragment=b'AP'+request[2:4]+len(body).to_bytes(2,'little')+binascii.crc_hqx(body,0xffff).to_bytes(2,'little')+body
                            sent=0
                            while sent<len(fragment):
                                buffer=C.create_string_buffer(fragment[sent:])
                                count=ws.send(sock,buffer,len(fragment)-sent,0)
                                if count<=0: raise RuntimeError('RFCOMM send failed')
                                sent+=count
                            header=receive(8); count=int.from_bytes(header[6:8],'little')
                            if header[0]!=0xac or count>512 or header[1:3]!=request[2:4]: raise RuntimeError('Bad SPP reply')
                            tail=receive(count+2)
                            if binascii.crc_hqx(header+tail[:-2],0xffff)!=int.from_bytes(tail[-2:],'little'): raise RuntimeError('SPP reply CRC failure')
                            result.extend(tail[:-2]); status=header[3]
                            if status:
                                failed=int.from_bytes(header[4:6],'little')
                                if failed!=0xffff: failed+=offset//3
                                break
                        header=b'\xac'+request[2:4]+bytes([status])+failed.to_bytes(2,'little')+len(result).to_bytes(2,'little')
                        reply=header+result
                        write_packet(handle,reply+binascii.crc_hqx(reply,0xffff).to_bytes(2,'little'))
                        timings.append((time.perf_counter()-started)*1000); packets+=1
                        if packets%300==0:
                            print(f'packets={packets} average roundtrip={sum(timings)/len(timings):.2f}ms max={max(timings):.2f}ms',flush=True); timings.clear()
                except EOFError:
                    print('Core disconnected',flush=True)
                finally:
                    kernel.DisconnectNamedPipe(handle)
        finally:
            kernel.CloseHandle(handle)
    finally:
        ws.closesocket(sock); ws.WSACleanup(); timer.timeEndPeriod(1)

if __name__=='__main__': main()
