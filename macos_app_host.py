"""Build local macOS app bundles backed by the user's existing Python installation."""
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import tempfile

# Ask the selected Python, since the project venv and launcher can have different bases.
_PROBE = """
import json, sys, sysconfig
from pathlib import Path
base = Path(sys.base_prefix)
framework = sysconfig.get_config_var("PYTHONFRAMEWORK") or "Python"
library = base / framework
if not library.is_file():
    library = Path(sysconfig.get_config_var("LIBDIR") or base) / (sysconfig.get_config_var("LDLIBRARY") or "")
if not library.is_file() or (library.name != framework and library.suffix != ".dylib"):
    raise SystemExit("A shared Python runtime is required. Install Python 3.13 from python.org.")
print(json.dumps(dict(library=str(library), executable=sys.executable, base_executable=sys._base_executable,
                      prefix=sys.prefix, base_prefix=sys.base_prefix, paths=sys.path)))
"""

# The py2app host embeds Python in the named GUI process. Use the real interpreter
# for pip and multiprocessing children, exactly as when starting with python -m.
_BOOT = '''import json, os, runpy, sys
from pathlib import Path

config = json.loads(Path(__file__).with_name("runtime.json").read_text(encoding="utf-8"))
sys.executable = config["executable"]
sys._base_executable = config["base_executable"]
sys.prefix = sys.exec_prefix = config["prefix"]
sys.base_prefix = sys.base_exec_prefix = config["base_prefix"]
sys.path[:] = [config["root"], *config["paths"]]
for key in ("PYTHONPATH", "RESOURCEPATH", "EXECUTABLEPATH", "ARGVZERO"):
    os.environ.pop(key, None)
os.chdir(config["root"])
if config["module"] is None:
    script = str(Path(config["root"]) / "uHandControlLauncher.pyw")
    sys.argv[:] = [script, "--desktop-window"]
    runpy.run_path(script, run_name="__main__")
else:
    sys.argv[:] = [config["module"]]
    runpy.run_module(config["module"], run_name="__main__", alter_sys=True)
'''


def icns_from_ico(icon):
    """Reuse the project's antialiased PNGs at their original resolutions."""
    data = icon.read_bytes()
    count = struct.unpack_from("<H", data, 4)[0]
    chunks = []
    sizes = {16: (b"icp4",), 32: (b"icp5", b"ic11"), 64: (b"icp6", b"ic12"),
             128: (b"ic07",), 256: (b"ic08", b"ic13")}
    for w, h, _, _, _, _, length, offset in struct.iter_unpack("<BBBBHHII", data[6:6+16*count]):
        png = data[offset:offset+length]
        if w == h and png.startswith(b"\x89PNG\r\n\x1a\n"):
            for tag in sizes.get(w or 256, ()):
                chunks.append(tag + struct.pack(">I", len(png) + 8) + png)
    if not chunks:
        raise ValueError(f"No PNG icon frames in {icon}")
    body = b"".join(chunks)
    return b"icns" + struct.pack(">I", len(body) + 8) + body


def app_command(root, name, module, interpreter, icon, version):
    probe = subprocess.run([str(interpreter), "-I", "-c", _PROBE], capture_output=True, text=True)
    if probe.returncode:
        raise RuntimeError(probe.stderr.strip() or "Could not inspect the selected Python.")
    config = json.loads(probe.stdout)
    config.update(root=str(root), module=module)
    settings = json.dumps(config, sort_keys=True)
    vendor = root / "assets/macos/py2app"
    template = vendor / "main-universal2"
    image = icns_from_ico(icon)
    info = plistlib.dumps({
        "CFBundlePackageType": "APPL", "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleIdentifier": f"com.github.SonYeongDong.uHandControl.{name}",
        "CFBundleName": name, "CFBundleDisplayName": name, "CFBundleExecutable": name,
        "CFBundleIconFile": "AppIcon.icns", "CFBundleVersion": version,
        "CFBundleShortVersionString": version, "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication", "PyMainFileNames": ["__boot__"],
        "PyRuntimeLocations": [config["library"]], "PyResourcePackages": [],
    })
    digest = hashlib.sha256(template.read_bytes() + info + image + _BOOT.encode() + settings.encode())
    cache = root / "build/macos-apps" / digest.hexdigest()[:20]
    bundle = cache / f"{name}.app"
    relative = Path("Contents/MacOS") / name
    if not (bundle / relative).is_file():
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache) as tmp:
            staged = Path(tmp) / bundle.name
            resources = staged / "Contents/Resources"
            resources.mkdir(parents=True)
            exe = staged / relative
            exe.parent.mkdir()
            shutil.copyfile(template, exe)
            exe.chmod(0o755)
            (exe.parent / "python").symlink_to(config["executable"])
            (staged / "Contents/Info.plist").write_bytes(info)
            (resources / "AppIcon.icns").write_bytes(image)
            (resources / "__boot__.py").write_text(_BOOT, encoding="utf-8")
            (resources / "runtime.json").write_text(settings, encoding="utf-8")
            shutil.copyfile(vendor / "LICENSE.txt", resources / "py2app-LICENSE.txt")
            sign = subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(staged)],
                                  capture_output=True, text=True)
            if sign.returncode:
                raise RuntimeError(f"macOS app signing failed: {sign.stderr.strip()}")
            try:
                staged.rename(bundle)
            except OSError:
                if not (bundle / relative).is_file():
                    raise
    return [str(bundle / relative)]


def app_for_process(command, cache, labels):
    """Match a GUI from this checkout, including hosts made by an older build."""
    path = Path(command)
    if len(path.parents) < 5 or path.parents[4] != cache:
        return None
    name = path.name
    if name in labels and path.parent.relative_to(path.parents[3]) == Path(f"{name}.app/Contents/MacOS"):
        return name
    return None
