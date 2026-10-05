"""Offline SPC validation, or a reset/IPL check for the assembled r0.4 board."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serial.tools import list_ports
from spc_play import SpcController, SpcFile, build_final_stub

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--port", help="Reset and check the SHVC-SOUND IPL on this COM port")
parser.add_argument("--spc", default=str(Path(__file__).resolve().parents[1] / "song.spc"))
args = parser.parse_args()
song = SpcFile(args.spc)
stub = build_final_stub(song, port_handshake=True)
print(f"SPC: {song.tags.get('game', '')} / {song.tags.get('title', '')}")
print(f"RAM: {len(song.ram)} bytes; DSP: {len(song.dsp)}; restore stub: {len(stub)}")
print(f"Restore stub overwrites RAM ${0xFFC0-len(stub):04X}-$FFBF; playback compatibility remains unverified.")
for port in list_ports.comports():
    print(f"{port.device}: {port.description} [{port.hwid}]")
if args.port:
    controller = SpcController(args.port)
    try:
        controller.set_volume(0)
        controller.reset()
        p0, p1 = controller.read_port(0), controller.read_port(1)
        print(f"IPL ports: {p0:02X} {p1:02X}")
        if (p0, p1) != (0xAA, 0xBB):
            raise RuntimeError("IPL is not ready")
        print("IPL OK. Reset leaves the amplifier at zero and MUTE asserted.")
    finally:
        controller.close()
