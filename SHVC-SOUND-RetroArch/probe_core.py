from pathlib import Path
import ctypes as C, json,time,argparse,os
p=argparse.ArgumentParser(); p.add_argument('--frames',type=int,default=600); p.add_argument('--port'); p.add_argument('--no-throttle',action='store_true'); a=p.parse_args()
ROOT=Path(__file__).resolve().parents[1]
if a.port: os.environ['SHVC_APU_PORT']=a.port; os.environ['SHVC_APU_LOG']=str(ROOT/'docs/tmp/real-apu.log')
core=C.CDLL(str(ROOT/'SHVC-SOUND-RetroArch/artifacts/snes9x_shvc_libretro.dll'))
Env=C.CFUNCTYPE(C.c_bool,C.c_uint,C.c_void_p)
Video=C.CFUNCTYPE(None,C.c_void_p,C.c_uint,C.c_uint,C.c_size_t)
Audio=C.CFUNCTYPE(None,C.c_int16,C.c_int16)
Batch=C.CFUNCTYPE(C.c_size_t,C.POINTER(C.c_int16),C.c_size_t)
Poll=C.CFUNCTYPE(None)
Input=C.CFUNCTYPE(C.c_int16,C.c_uint,C.c_uint,C.c_uint,C.c_uint)
class Game(C.Structure): _fields_=[('path',C.c_char_p),('data',C.c_void_p),('size',C.c_size_t),('meta',C.c_char_p)]
class Timing(C.Structure): _fields_=[('fps',C.c_double),('sample_rate',C.c_double)]
class Geometry(C.Structure): _fields_=[('bw',C.c_uint),('bh',C.c_uint),('mw',C.c_uint),('mh',C.c_uint),('aspect',C.c_float)]
class AV(C.Structure): _fields_=[('geometry',Geometry),('timing',Timing)]
strings=[]; frame=0; images=0; samples=0
@Env
def env(cmd,data):
 if cmd in (9,31):
  s=str(ROOT/'docs/tmp').encode(); strings.append(s); C.cast(data,C.POINTER(C.c_char_p))[0]=s; return True
 if cmd==10: return C.cast(data,C.POINTER(C.c_int))[0] in (0,2)
 if cmd==17: C.cast(data,C.POINTER(C.c_bool))[0]=False; return True
 if cmd in (15,27,39,52): return False
 if cmd in (16,35,36,37,51,53,69): return True
 return False
@Video
def video(data,w,h,pitch):
 global images
 if data:
  images+=1
  if frame in (180,360,599):
   from PIL import Image
   import numpy as np
   raw=C.string_at(data,pitch*h); pixels=np.frombuffer(raw,dtype='<u2').reshape(h,pitch//2)[:,:w]
   rgb=np.stack((((pixels>>11)&31)*255//31,((pixels>>5)&63)*255//63,(pixels&31)*255//31),axis=2).astype('uint8')
   Image.fromarray(rgb).save(ROOT/f'docs/tmp/smw-frame-{frame}.png')
@Audio
def audio(l,r): pass
@Batch
def batch(data,count):
 global samples
 samples+=count; return count
@Poll
def poll(): pass
@Input
def input_state(port,device,index,id):
 # Title and game selection progression. No input before title screenshot.
 buttons=(1<<3) if frame in range(400,404) or frame in range(450,454) else 0
 return buttons if id==256 else int(bool(buttons&(1<<id)))
callbacks=[env,video,audio,batch,poll,input_state]
for name,cb in zip(['environment','video_refresh','audio_sample','audio_sample_batch','input_poll','input_state'],callbacks):
 fn=getattr(core,'retro_set_'+name); fn.argtypes=[type(cb)]; fn(cb)
core.retro_init()
rom=ROOT.parents[2]/'SFC-ROM/SuperMarioWorld.sfc'; blob=C.create_string_buffer(rom.read_bytes())
print('ROM bytes',len(blob)-1,'title',rom.read_bytes()[0x7fc0:0x7fd5].decode('ascii',errors='replace'),flush=True)
info=Game(str(rom).encode('utf-8'),C.cast(blob,C.c_void_p),len(blob)-1,None)
core.retro_load_game.argtypes=[C.POINTER(Game)]; core.retro_load_game.restype=C.c_bool
assert core.retro_load_game(C.byref(info))
av=AV(); core.retro_get_system_av_info.argtypes=[C.POINTER(AV)]; core.retro_get_system_av_info(C.byref(av))
print('fps',av.timing.fps,flush=True); started=time.perf_counter()
for frame in range(a.frames):
 core.retro_run()
 if frame==300: steady_started=time.perf_counter()
 if frame%60==0: print('frame',frame,'seconds',round(time.perf_counter()-started,3),'debug',[hex(core.shvc_debug(i)) for i in range(7)],flush=True)
 if a.port and not a.no_throttle: time.sleep(max(0,started+(frame+1)/av.timing.fps-time.perf_counter()))
if a.port:
 assert core.shvc_debug(7)==0, 'Real hardware transport failed; emulated fallback is not a valid benchmark'
core.retro_unload_game(); core.retro_deinit()
print(json.dumps({'frames':a.frames,'images':images,'audioFrames':samples,'seconds':time.perf_counter()-started,'steady_fps':(a.frames-301)/(time.perf_counter()-steady_started) if a.frames>301 else None}))
