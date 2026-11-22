"""Build application-specific Windows GUI hosts from the user's CPython installation."""
import ctypes
from ctypes import wintypes as W
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import shutil
import struct
import tempfile


def _version_info(name, version):
    """Encode a standard VS_VERSION_INFO resource with Unicode string tables."""
    def wide(text):
        return (text + "\0").encode("utf-16le")

    def aligned(data):
        return data + b"\0" * (-len(data) % 4)

    def block(key, value=b"", children=(), text=False):
        body = aligned(b"\0" * 6 + wide(key)) + value
        for child in children:
            body = aligned(body) + child
        return struct.pack("<HHH", len(body), len(value) // (2 if text else 1), int(text)) + body[6:]

    major, minor, patch = map(int, version.split("."))
    high, low = major << 16 | minor, patch << 16
    fixed = struct.pack("<13I", 0xFEEF04BD, 0x10000, high, low, high, low, 0x3F,
                        0x04, 0x40004, 1, 0, 0, 0)
    strings = {"FileDescription": name, "ProductName": name, "InternalName": name,
               "OriginalFilename": name + ".exe", "FileVersion": version,
               "ProductVersion": version, "Comments": "uHandControl GUI host for CPython"}
    table = block("040904b0", children=[block(k, wide(v), text=True) for k, v in strings.items()], text=True)
    translation = block("Translation", struct.pack("<HH", 0x409, 1200))
    return block("VS_VERSION_INFO", fixed, [block("StringFileInfo", children=[table], text=True),
                                             block("VarFileInfo", children=[translation], text=True)])


def _resources(exe, icon, version):
    api = ctypes.WinDLL("kernel32", use_last_error=True)

    def function(name, result, *args):
        fn = getattr(api, name)
        fn.argtypes, fn.restype = args, result
        def checked(*values):
            value = fn(*values)
            if not value:
                raise ctypes.WinError(ctypes.get_last_error())
            return value
        return checked

    # Keep the interpreter's original application manifest (including its DPI and path settings).
    load = function("LoadLibraryExW", W.HMODULE, W.LPCWSTR, W.HANDLE, W.DWORD)
    find = function("FindResourceW", W.HANDLE, W.HMODULE, W.LPVOID, W.LPVOID)
    module = load(str(exe), None, 2)  # LOAD_LIBRARY_AS_DATAFILE
    try:
        res = find(module, 1, 24)  # RT_MANIFEST
        size = function("SizeofResource", W.DWORD, W.HMODULE, W.HANDLE)(module, res)
        loaded = function("LoadResource", W.HANDLE, W.HMODULE, W.HANDLE)(module, res)
        manifest = ctypes.string_at(function("LockResource", W.LPVOID, W.HANDLE)(loaded), size)
    finally:
        function("FreeLibrary", W.BOOL, W.HMODULE)(module)

    begin = function("BeginUpdateResourceW", W.HANDLE, W.LPCWSTR, W.BOOL)
    update = function("UpdateResourceW", W.BOOL, W.HANDLE, W.LPVOID, W.LPVOID, W.WORD, W.LPVOID, W.DWORD)
    end = function("EndUpdateResourceW", W.BOOL, W.HANDLE, W.BOOL)
    handle = begin(str(exe), True)
    def put(kind, index, data):
        update(handle, kind, index, 0x409, data, len(data))
    try:
        put(24, 1, manifest)
        put(16, 1, _version_info(exe.stem, version))
        group = bytearray(icon[:6])
        count = struct.unpack_from("<H", icon, 4)[0]
        for i in range(count):
            pos = 6 + 16 * i
            length, offset = struct.unpack_from("<II", icon, pos + 8)
            put(3, i + 1, icon[offset:offset + length])
            group.extend(icon[pos:pos + 12] + struct.pack("<H", i + 1))
        put(14, 1, bytes(group))
    except BaseException:
        end(handle, True)
        raise
    end(handle, False)


@lru_cache
def gui_host(cache, base, icons, version):
    """Publish a complete per-runtime set atomically, also for simultaneous first launches."""
    template = base / "pythonw.exe"
    artwork = [(name, path.read_bytes()) for name, path in icons]
    dlls = sorted({*base.glob("python3*.dll"), *base.glob("vcruntime*.dll")})
    digest = hashlib.sha256(Path(__file__).read_bytes())
    digest.update(str(template).encode("utf-8"))
    digest.update(template.read_bytes())
    digest.update(version.encode("ascii"))
    for dll in dlls:
        info = dll.stat()
        digest.update(f"{dll.name}:{info.st_size}:{info.st_mtime_ns}".encode("ascii"))
    for name, icon in artwork:
        digest.update(name.encode("ascii") + icon)
    destination = cache / digest.hexdigest()[:20]
    if destination.is_dir():
        return destination

    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache) as temporary:
        stage = Path(temporary) / "hosts"
        stage.mkdir()
        for dll in dlls:
            shutil.copy2(dll, stage / dll.name)
        for name, icon in artwork:
            exe = stage / (name + ".exe")
            shutil.copyfile(template, exe)
            _resources(exe, icon, version)
        try:
            stage.rename(destination)
        except OSError:
            if not destination.is_dir():
                raise
    return destination


def host_command(name, base, interpreter, cache, icons, version, args):
    directory = gui_host(cache, base, icons, version)
    # CPython's Windows venv redirector passes this same variable to its child.
    # Keep sys.executable and package lookup in the original environment.
    return [str(directory / (name + ".exe")), *args], dict(os.environ, __PYVENV_LAUNCHER__=str(interpreter))
