"""Add the two classic-ESP32 dependencies to this PC's existing C6 toolchain."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile

ROOT = Path(r"C:\Users\Yugo\esp")
INDEX = ROOT / "arduino15/package_esp32_index.json"

def install(name, version):
    package = json.loads(INDEX.read_text())["packages"][0]
    tool = next(t for t in package["tools"] if t["name"] == name and t["version"] == version)
    system = next(s for s in tool["systems"] if s["host"] == "x86_64-mingw32")
    target = ROOT / "arduino15/packages/esp32/tools" / name / version
    if target.exists():
        print(f"Already installed: {name}", flush=True)
        return
    archive = ROOT / "dl" / system["archiveFileName"]
    archive.parent.mkdir(parents=True, exist_ok=True)
    expected = system["checksum"].split(":", 1)[1].lower()
    def digest(path):
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    if not archive.exists() or digest(archive) != expected:
        print(f"Downloading {name}: {int(system['size']) / 2**20:.1f} MiB", flush=True)
        # Resolve the signed GitHub asset URL once before parallel range requests.
        with urllib.request.urlopen(urllib.request.Request(system["url"], method="HEAD"), timeout=60) as response:
            asset_url = response.url
        size = int(system["size"])
        pieces = 8
        def fetch(i):
            start, end = size * i // pieces, size * (i + 1) // pieces - 1
            part = archive.with_suffix(f".part{i}")
            request = urllib.request.Request(asset_url, headers={"Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(request, timeout=120) as response:
                if response.status != 206:
                    raise RuntimeError("Server did not accept a range download")
                if response.headers.get("Content-Range") != f"bytes {start}-{end}/{size}":
                    raise RuntimeError("Unexpected Content-Range")
                with part.open("wb") as stream:
                    shutil.copyfileobj(response, stream)
            if part.stat().st_size != end - start + 1:
                raise RuntimeError("Incomplete download")
            print(f"{name}: part {i + 1}/8 complete", flush=True)
            return part
        with concurrent.futures.ThreadPoolExecutor(max_workers=pieces) as executor:
            parts = list(executor.map(fetch, range(pieces)))
        with archive.open("wb") as stream:
            for part in parts:
                with part.open("rb") as source:
                    shutil.copyfileobj(source, stream)
                part.unlink()
        if digest(archive) != expected:
            raise RuntimeError(f"Checksum mismatch for {name}")
    print(f"Verified SHA256: {name}; extracting", flush=True)
    with zipfile.ZipFile(archive) as source:
        roots = {info.filename.split('/')[0] for info in source.infolist() if info.filename}
        if len(roots) != 1:
            raise RuntimeError("Expected a single archive root")
        prefix = next(iter(roots)) + "/"
        for info in source.infolist():
            relative = info.filename.removeprefix(prefix)
            if not relative or relative == prefix.rstrip('/'):
                continue
            path = target / relative
            if not path.resolve().is_relative_to(target.resolve()):
                raise RuntimeError("Unsafe archive path")
            if info.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with source.open(info) as stream, path.open("wb") as output:
                    shutil.copyfileobj(stream, output)
    print(f"Installed {name} {version}", flush=True)

if __name__ == "__main__":
    install("esp-x32", "2601")
    install("esp32-libs", "3.3.12")
