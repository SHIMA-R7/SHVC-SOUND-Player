"""Provision a debuggable private RetroArch test APK; never bundle a ROM."""
from pathlib import Path
import argparse,hashlib,json,subprocess,tempfile,zipfile
p=argparse.ArgumentParser();p.add_argument('--device',required=True);p.add_argument('--host',required=True);p.add_argument('--rom',type=Path,required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[1]
base=Path(tempfile.gettempdir())/'shvc-android-tools'
config=json.loads((base/'tools.json').read_text(encoding='utf-8-sig'))
adb=[str(Path(config['sdk'])/'platform-tools/adb.exe'),'-s',a.device];package='com.retroarch.aarch64';private='/data/user/0/'+package+'/files'
def run(*args,**kwargs):return subprocess.run([*adb,*args],check=True,**kwargs)
run('shell','run-as',package,'mkdir','-p','files/cores','files/info','files/saves','files/system','files/games','files/logs','files/assets')
def copy(source,destination):
 staged='/data/local/tmp/shvc-ra-provision'
 try:
  run('push',str(source),staged,stdout=subprocess.DEVNULL)
  run('shell','run-as',package,'cp',staged,destination)
 finally:run('shell','rm','-f',staged)
copy(root/'SHVC-SOUND-Android-SFC/app/src/main/jniLibs/arm64-v8a/libshvc_core.so','files/cores/snes9x_shvc_libretro_android.so')
copy(a.rom,'files/games/game.sfc')
digest=run('shell','run-as',package,'sha256sum','files/games/game.sfc',capture_output=True,text=True).stdout.split()[0]
assert digest==hashlib.sha256(a.rom.read_bytes()).hexdigest()
work=base/'ra-provision';work.mkdir(exist_ok=True)
(work/'shvc-wifi.txt').write_text(a.host+'\n',encoding='utf-8');copy(work/'shvc-wifi.txt','files/system/shvc-wifi.txt')
info='''display_name = "Nintendo - SNES (Snes9x SHVC WiFi)"
corename = "Snes9x SHVC WiFi"
supported_extensions = "smc|sfc|swc|fig"
authors = "Snes9x Team"
systemname = "Super Nintendo Entertainment System"
systemid = "snes"
supports_no_game = "false"
'''
(work/'core.info').write_text(info,encoding='utf-8');copy(work/'core.info','files/info/snes9x_shvc_libretro.info');copy(work/'core.info','files/info/snes9x_shvc_libretro_android.info')
with zipfile.ZipFile(base/'RetroArch_aarch64.apk') as z:
 for n in z.namelist():
  if n.startswith('assets/overlays/gamepads/snes/') and not n.endswith('/'):
   file=work/n;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(z.read(n))
run('push',str(work/'assets/overlays'),'/data/local/tmp/shvc-ra-overlays',stdout=subprocess.DEVNULL)
run('shell','run-as',package,'cp','-r','/data/local/tmp/shvc-ra-overlays','files/assets/overlays')
run('shell','rm','-r','/data/local/tmp/shvc-ra-overlays')
overlay=next((work/'assets/overlays/gamepads/snes').glob('*.cfg')).name
cfg=f'''audio_enable = "false"
audio_sync = "false"
video_driver = "gl"
video_vsync = "true"
video_threaded = "true"
video_fullscreen = "true"
video_scale_integer = "false"
aspect_ratio_index = "0"
menu_driver = "glui"
input_overlay_enable = "true"
input_overlay_opacity = "0.65"
input_overlay = "{private}/assets/overlays/gamepads/snes/{overlay}"
input_overlay_hide_in_menu = "true"
input_overlay_show_physical_inputs = "false"
input_autodetect_enable = "true"
input_menu_toggle_gamepad_combo = "1"
menu_pause_libretro = "false"
rewind_enable = "false"
run_ahead_enabled = "false"
savestate_auto_load = "false"
savestate_auto_save = "false"
config_save_on_exit = "true"
log_verbosity = "true"
log_to_file = "true"
log_to_file_timestamp = "false"
log_dir = "{private}/logs"
system_directory = "{private}/system"
savefile_directory = "{private}/saves"
savestate_directory = "{private}/saves"
libretro_directory = "{private}/cores"
libretro_info_path = "{private}/info"
core_options_path = "{private}/retroarch-core-options.cfg"
rgui_browser_directory = "{private}/games"
'''
(work/'retroarch.cfg').write_text(cfg,encoding='utf-8');copy(work/'retroarch.cfg','files/retroarch.cfg')
(work/'options.cfg').write_text('shvc_wifi_address = "file"\n',encoding='utf-8');copy(work/'options.cfg','files/retroarch-core-options.cfg')
run('shell','am','start','-n',package+'/com.retroarch.browser.retroactivity.RetroActivityFuture','--es','CONFIGFILE',private+'/retroarch.cfg','--es','LIBRETRO',private+'/cores/snes9x_shvc_libretro_android.so','--es','ROM',private+'/games/game.sfc','--ez','QUITFOCUS','true')
