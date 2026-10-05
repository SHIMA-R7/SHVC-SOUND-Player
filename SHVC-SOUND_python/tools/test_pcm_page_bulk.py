"""Verify page-bounded SPC700 bulk writes at every page offset and ring wrap."""
import pcm_stream as m

m.selftest()
for low in range(256):
    sim=m.Sim()
    sim.ram[2:8]=bytes([low,5,0,4,0,6])
    for _ in range(3): sim.step()
    payload=bytes((i*37+low)&255 for i in range(513))
    done=0; ptr=0x500+low
    while done<len(payload):
        n=min((len(payload)-done)//3*3,((255-(ptr&255))//3)*3)
        if n>=3:
            assert sim.host_command(9,idle="fbloop")
            seq=sim.host_in[0]
            for off in range(done,done+n,3):
                seq=(seq+1)&255 or 1
                sim.host_in[1:4]=payload[off:off+3]; sim.host_in[0]=seq
                for _ in range(200):
                    sim.step()
                    if sim.out[0]==seq and sim.pc==m.DRIVER_LABELS["fbloop"]: break
                else: raise AssertionError("fast ACK")
            sim.host_in[0]=0
            for _ in range(200):
                sim.step()
                if sim.out[0]==0 and sim.pc==m.DRIVER_LABELS["loop"]: break
            else: raise AssertionError("fast exit")
        else:
            n=min(2,len(payload)-done,256-(ptr&255))
            assert sim.host_command(n,payload[done],payload[done+1] if n==2 else 0)
        done+=n; ptr+=n
        if ptr>=0x600: ptr=0x400+ptr-0x600
        assert (sim.ram[2]|sim.ram[3]<<8)==ptr
    expected=bytearray(512)
    for i,v in enumerate(payload): expected[(256+low+i)%512]=v
    assert sim.ram[0x400:0x600]==expected
    assert sim.sp==0xEF
print("Page bulk: 256 offsets and ring wrap passed")
