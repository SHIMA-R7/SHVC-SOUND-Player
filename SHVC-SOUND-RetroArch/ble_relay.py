"""Local Windows named pipe -> BLE real-APU packet relay. No ROM data."""
import asyncio
import ctypes as C
from ctypes import wintypes as W
import time
from bleak import BleakClient, BleakScanner

SERVICE='587a0001-5356-4348-8000-00805f9b34fb'
TX='587a0002-5356-4348-8000-00805f9b34fb'
RX='587a0003-5356-4348-8000-00805f9b34fb'
kernel=C.WinDLL('kernel32',use_last_error=True)
kernel.CreateNamedPipeW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,C.c_void_p]
kernel.CreateNamedPipeW.restype=W.HANDLE
kernel.ConnectNamedPipe.argtypes=[W.HANDLE,C.c_void_p]
kernel.ReadFile.argtypes=[W.HANDLE,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.c_void_p]
kernel.WriteFile.argtypes=kernel.ReadFile.argtypes
kernel.DisconnectNamedPipe.argtypes=[W.HANDLE]
kernel.CloseHandle.argtypes=[W.HANDLE]

def connect_pipe(handle):
    ok=kernel.ConnectNamedPipe(handle,None)
    if not ok and C.get_last_error()!=535: raise C.WinError(C.get_last_error())

def read_exact(handle,count):
    data=bytearray()
    while len(data)<count:
        buffer=C.create_string_buffer(count-len(data)); got=W.DWORD()
        if not kernel.ReadFile(handle,buffer,len(buffer),C.byref(got),None) or not got.value:
            raise EOFError('Core disconnected')
        data.extend(buffer.raw[:got.value])
    return bytes(data)

def read_packet(handle):
    header=read_exact(handle,8)
    if header[:2]!=b'AP': raise ValueError('Bad request marker')
    count=int.from_bytes(header[4:6],'little')
    if count>1536 or count%3: raise ValueError('Bad request length')
    return header+read_exact(handle,count)

def write_packet(handle,data):
    sent=W.DWORD(); buffer=C.create_string_buffer(data)
    if not kernel.WriteFile(handle,buffer,len(data),C.byref(sent),None) or sent.value!=len(data):
        raise EOFError('Pipe write failed')

async def main():
    device=await BleakScanner.find_device_by_filter(
        lambda d,a: SERVICE in [s.lower() for s in a.service_uuids],timeout=20)
    if not device: raise RuntimeError('SHVC-APU Bridge was not found')
    notifications=asyncio.Queue(); pending=bytearray()
    def notify(_,data):
        pending.extend(data)
        if len(pending)>=8:
            count=int.from_bytes(pending[6:8],'little')
            if count>512: raise ValueError('Bad BLE reply length')
            if len(pending)>=count+10:
                notifications.put_nowait(bytes(pending[:count+10])); del pending[:count+10]
    async with BleakClient(device,timeout=20) as client:
        from winrt.windows.devices.bluetooth import BluetoothLEPreferredConnectionParameters
        native=client._backend._requester
        preference=native.request_preferred_connection_parameters(BluetoothLEPreferredConnectionParameters.throughput_optimized)
        await asyncio.sleep(2)
        actual=native.get_connection_parameters()
        print(f'Windows BLE interval={actual.connection_interval*1.25:.2f}ms latency={actual.connection_latency} request={preference.status}',flush=True)
        await client.start_notify(RX,notify)
        characteristic=client.services.get_characteristic(TX)
        await asyncio.sleep(1)
        chunk=min(180,characteristic.max_write_without_response_size)
        print(f'BLE connected {device.address}, write chunk={chunk}',flush=True)
        handle=kernel.CreateNamedPipeW(r'\\.\pipe\shvc-apu-ble',3,0,1,8192,8192,0,None)
        if handle==W.HANDLE(-1).value: raise C.WinError(C.get_last_error())
        try:
            while client.is_connected:
                print('READY: launch core with SHVC_APU_PORT=BLE',flush=True)
                await asyncio.to_thread(connect_pipe,handle)
                timings=[]; packets=0
                try:
                    while client.is_connected:
                        request=await asyncio.to_thread(read_packet,handle)
                        started=time.perf_counter()
                        for offset in range(0,len(request),chunk):
                            await client.write_gatt_char(characteristic,request[offset:offset+chunk],response=False)
                        reply=await asyncio.wait_for(notifications.get(),3)
                        await asyncio.to_thread(write_packet,handle,reply)
                        timings.append((time.perf_counter()-started)*1000); packets+=1
                        if packets%300==0:
                            print(f'packets={packets} average roundtrip={sum(timings)/len(timings):.2f}ms max={max(timings):.2f}ms',flush=True); timings.clear()
                except EOFError:
                    print('Core disconnected',flush=True)
                finally:
                    kernel.DisconnectNamedPipe(handle)
        finally:
            kernel.CloseHandle(handle)

if __name__=='__main__':
    asyncio.run(main())
