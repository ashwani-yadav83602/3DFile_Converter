"""
JT converter server.

  GET  /health                      -> is Aspose.3D usable? (shows the real error if not)
  POST /probe                       -> multipart field "file" (.jt); looks for color data inside the JT itself
  POST /inspect                     -> multipart field "file" (.jt); shows the materials Aspose reads
  POST /convert?format=gltf|glb     -> multipart field "file" (.jt); returns the converted file
                                       (a .zip if the .gltf comes with extra files like .bin)
  POST /upload                      -> converts to .glb (once per unique file), returns {"url": ...}
  POST /add-to-jt2go                -> opens the uploaded .jt in Siemens JT2Go
  GET  /models/<name>               -> serves converted .glb files for the viewer
  GET  /                            -> serves index.html (the viewer page)

Run with the venv Python:
  C:\\Project\\new\\venv\\Scripts\\python.exe converter_server.py

Test the color question with curl.exe (PowerShell):
  curl.exe -F "file=@C:\\Users\\Ashwin\\Desktop\\A23.jt" http://127.0.0.1:5000/probe
"""
import hashlib
import io
import os
import re
import shutil
import struct
import uuid
import zipfile
import zlib
import subprocess
from collections import Counter
from pathlib import Path


from flask import Flask, Response, jsonify, request, send_file, send_from_directory
from werkzeug.utils import secure_filename


JT2GO_EXE = os.environ.get("JT2GO_EXE")

BASE = Path(__file__).parent
UPLOADS = BASE / "uploads"
CONVERTED = BASE / "converted"
UPLOADS.mkdir(exist_ok=True)
CONVERTED.mkdir(exist_ok=True)

MIMETYPES = {
    "glb": "model/gltf-binary",
    "gltf": "model/gltf+json",
    "zip": "application/zip",
}

# Bump this whenever convert_jt() changes. It is part of the cache key, so files
# converted by an older version (for example the all-white ones) are converted again.
CONVERTER_VERSION = "aspose-pbr-v1"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB upload limit


@app.after_request
def add_cors(resp):
    # Only needed if another website calls this API. Example: set CORS_ORIGIN=http://localhost:3000
    origin = os.environ.get("CORS_ORIGIN")
    if origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
    return resp


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------
def load_aspose():
    """Return (module, None) or (None, readable error). Imported lazily so /health can report problems."""
    try:
        import aspose.threed as a3d
        return a3d, None
    except Exception as e:  # ImportError, missing DLLs, unsupported Python, ...
        return None, f"{type(e).__name__}: {e}"


def _legacy_rgb(old):
    """Pull an RGB triple out of a CAD/legacy material, or None if it has no usable color."""
    for attr in ("diffuse_color", "albedo", "ambient_color", "specular_color"):
        val = getattr(old, attr, None)
        if val is not None and hasattr(val, "x"):
            return val.x, val.y, val.z
    return None


def convert_jt(src: Path, dst: Path) -> dict:
    """
    Convert .jt to .glb/.gltf (format chosen by dst's extension).

    Materials that Aspose read from the JT are converted to glTF PBR materials so the
    color survives in the browser. Colors that Aspose did NOT read cannot be recovered here.
    Returns a small stats dict (also logged).
    """
    a3d, err = load_aspose()
    if a3d is None:
        raise RuntimeError(f"Aspose.3D could not be loaded ({err})")

    scene = a3d.Scene.from_file(str(src))
    stats = {"nodes": 0, "with_material": 0, "converted": 0}

    def walk(node):
        stats["nodes"] += 1
        old = node.material  # first material of the node, or None
        if old is not None:
            stats["with_material"] += 1
            already_pbr = isinstance(old, a3d.shading.PbrMaterial)
            rgb = None if already_pbr else _legacy_rgb(old)
            if rgb is not None:
                pbr = a3d.shading.PbrMaterial()
                pbr.albedo = a3d.utilities.Vector3(rgb[0], rgb[1], rgb[2])
                pbr.metallic_factor = 0.1
                pbr.roughness_factor = 0.5
                pbr.name = getattr(old, "name", None) or "MappedMaterial"
                node.material = pbr
                stats["converted"] += 1
        for child in node.child_nodes:
            walk(child)

    walk(scene.root_node)

    if stats["with_material"] == 0:
        app.logger.warning(
            "Aspose found NO materials in %s - the .glb will have no color. "
            "A JT reader that supports colors is needed for this file.", src.name
        )
    else:
        app.logger.info("JT materials: %s", stats)

    # The format is picked from the file extension (.glb / .gltf)
    scene.save(str(dst))

    if not dst.exists():
        raise RuntimeError("Conversion finished but no output file was produced.")
    return stats


# --------------------------------------------------------------------------
# JT probe: look for color data inside the JT file itself (independent of Aspose)
# --------------------------------------------------------------------------
JT_END_GUID = b"\xff" * 16
JT_MATERIAL_GUID_STR = "10dd1030-2ac8-11d1-9b6b-0080c7bb2597"
# The same GUID as it is stored on disk (first three fields little-endian)
JT_MATERIAL_GUID = struct.pack("<IHH", 0x10DD1030, 0x2AC8, 0x11D1) + bytes.fromhex("9b6b0080c7bb2597")

JT_ELEMENT_NAMES = {
    "10dd1030-2ac8-11d1-9b6b-0080c7bb2597": "Material Attribute  <-- COLORS",
    "10dd101b-2ac8-11d1-9b6b-0080c7bb2597": "Group Node",
    "10dd102a-2ac8-11d1-9b6b-0080c7bb2597": "Instance Node",
    "10dd1083-2ac8-11d1-9b6b-0080c7bb2597": "Geometric Transform Attribute",
    "ce357244-38fb-11d1-a506-0060971bdc6d": "Part Node",
    "ce357245-38fb-11d1-a506-0060971bdc6d": "Meta Data Node",
    "ce357249-38fb-11d1-a506-0060971bdc6d": "Partition Node",
}
JT_SEGMENT_TYPES = {1: "Logical Scene Graph", 2: "JT B-Rep", 3: "PMI Data", 4: "Meta Data",
                    6: "Shape", 17: "Shape LOD", 18: "Shape LOD"}


def _guid_str(b):
    d1, d2, d3 = struct.unpack("<IHH", b[:8])
    return f"{d1:08x}-{d2:04x}-{d3:04x}-{b[8:10].hex()}-{b[10:16].hex()}"


def _hexdump(b, width=16, limit=96):
    b = bytes(b[:limit])
    return "\n".join(f"    {i:04x}  {b[i:i + width].hex(' ')}" for i in range(0, len(b), width))


def _color_candidates(body):
    """Places where 4 consecutive little-endian floats all lie in [0, 1] (possible RGBA colors)."""
    found, last_end = [], -1
    body = bytes(body)
    for i in range(0, len(body) - 15):
        if i < last_end:
            continue
        r, g, b, a = struct.unpack_from("<4f", body, i)
        if all(0.0 <= v <= 1.0001 for v in (r, g, b, a)) and max(r, g, b) > 0.001 and a > 0.001:
            found.append((i, tuple(round(v, 3) for v in (r, g, b, a))))
            last_end = i + 16
    return found


def _inflate_any(payload):
    for off in range(0, min(len(payload) - 2, 64)):
        if payload[off] == 0x78 and payload[off + 1] in (0x01, 0x5E, 0x9C, 0xDA):
            try:
                out = zlib.decompressobj().decompress(payload[off:])
                if out:
                    return out
            except zlib.error:
                continue
    return None


def _structured_probe(data, say):
    """Read header, table of contents and the scene-graph segment the way the JT spec describes."""
    m = re.search(rb"Version\s+(\d+)\.(\d+)", data[:80])
    if not m:
        say("Header: no 'Version x.y' text found - this may not be a JT file.")
        return
    major, minor = int(m.group(1)), int(m.group(2))
    byte_order = data[80]
    pos = 85  # 80 version + 1 byte order + 4 reserved
    if major >= 10:
        toc_offset = struct.unpack_from("<q", data, pos)[0]
        pos += 8
    else:
        toc_offset = struct.unpack_from("<i", data, pos)[0]
        pos += 4
    lsg_guid = _guid_str(data[pos:pos + 16])
    say(f"JT version {major}.{minor}, byte order {'little-endian' if byte_order == 0 else 'BIG-ENDIAN'}, TOC offset {toc_offset}")
    if byte_order != 0:
        say("Big-endian files are not handled by this probe.")
        return

    count = struct.unpack_from("<i", data, toc_offset)[0]
    pos = toc_offset + 4
    entries = []
    for _ in range(count):
        gid = _guid_str(data[pos:pos + 16])
        pos += 16
        if major >= 10:
            off = struct.unpack_from("<q", data, pos)[0]
            pos += 8
        else:
            off = struct.unpack_from("<i", data, pos)[0]
            pos += 4
        length, attrs = struct.unpack_from("<II", data, pos)
        pos += 8
        entries.append({"guid": gid, "offset": off, "length": length, "type": attrs >> 24})
    say(f"Segments: {len(entries)}")
    for t, n in sorted(Counter(e["type"] for e in entries).items()):
        say(f"  type {t:>3} {JT_SEGMENT_TYPES.get(t, 'other'):<22} x{n}")

    lsg = next((e for e in entries if e["guid"] == lsg_guid), None) or next((e for e in entries if e["type"] == 1), None)
    if lsg is None:
        say("No Logical Scene Graph segment found.")
        return
    payload = data[lsg["offset"] + 24: lsg["offset"] + max(lsg["length"], 24)]
    buf = _inflate_any(payload) or payload
    say(f"Scene-graph segment: {len(buf):,} bytes")

    counts, pos = Counter(), 0
    while pos + 20 <= len(buf):
        elen = struct.unpack_from("<i", buf, pos)[0]
        if elen < 16 or pos + 4 + elen > len(buf):
            break
        g = buf[pos + 4: pos + 20]
        if g != JT_END_GUID:
            counts[_guid_str(g)] += 1
        pos += 4 + elen
    say(f"Scene-graph elements: {sum(counts.values())}")
    for g, n in counts.most_common(15):
        say(f"  x{n:<5} {g}  {JT_ELEMENT_NAMES.get(g, '')}")
    say(f"Material Attribute elements in scene graph: {counts.get(JT_MATERIAL_GUID_STR, 0)}")


def _scan_probe(data, say):
    """Independent check: inflate every zlib stream in the file and look for Material Attribute GUIDs."""
    mv = memoryview(data)
    tried = inflated = hits = shown = 0
    colors = Counter()
    for m in re.finditer(rb"\x78[\x01\x5e\x9c\xda]", data):
        tried += 1
        if tried > 50000:
            say("(stopped scanning after 50000 candidate streams)")
            break
        try:
            chunk = zlib.decompressobj().decompress(mv[m.start(): m.start() + 4_000_000], 16_000_000)
        except zlib.error:
            continue
        if len(chunk) < 20:
            continue
        inflated += 1
        pos = 0
        while True:
            i = chunk.find(JT_MATERIAL_GUID, pos)
            if i < 0:
                break
            hits += 1
            body = chunk[i + 16: i + 16 + 120]
            cands = _color_candidates(body)
            for _, c in cands:
                colors[c] += 1
            if shown < 3:
                say(f"  Material data #{hits} (120 bytes after the GUID):")
                say(_hexdump(body, limit=120))
                say(f"    RGBA-looking values: {cands[:5]}")
                shown += 1
            pos = i + 16
    say(f"Scan: {tried} candidate streams, {inflated} inflated, Material Attribute GUID found {hits} times")
    if colors:
        say(f"Distinct RGBA-looking values near those GUIDs: {len(colors)}")
        for c, n in colors.most_common(15):
            say(f"  RGBA {c}  x{n}")


def probe_jt(data: bytes) -> list:
    out = []
    say = out.append
    say(f"File size: {len(data):,} bytes")
    say("First 96 bytes: " + data[:96].hex(" "))
    say("")
    say("== Structured read (header / table of contents / scene graph) ==")
    try:
        _structured_probe(data, say)
    except Exception as e:
        say(f"Structured read failed: {type(e).__name__}: {e}")
    say("")
    say("== Brute-force scan of all compressed data ==")
    try:
        _scan_probe(data, say)
    except Exception as e:
        say(f"Scan failed: {type(e).__name__}: {e}")
    return out


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def check_upload():
    """Validate the uploaded file. Returns (file, error_response)."""
    file = request.files.get("file")
    if not file or not file.filename:
        return None, (jsonify(error="No file selected."), 400)
    if not file.filename.lower().endswith(".jt"):
        return None, (jsonify(error="Only .jt files are allowed."), 400)
    return file, None


def find_jt2go_executable():
    """Find JT2Go without relying on the potentially incorrect .jt file association."""
    candidates = [JT2GO_EXE] if JT2GO_EXE else []
    for program_files in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if program_files:
            candidates.append(str(Path(program_files) / "Siemens" / "JT2Go" / "JT2Go.exe"))

    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))

    if os.name == "nt":
        import winreg

        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(
                    hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\JT2Go.exe"
                ) as key:
                    executable, _ = winreg.QueryValueEx(key, None)
                if executable and Path(executable).is_file():
                    return executable
            except OSError:
                pass

        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ".jt") as key:
                prog_id, _ = winreg.QueryValueEx(key, None)
            with winreg.OpenKey(
                winreg.HKEY_CLASSES_ROOT, prog_id + r"\shell\open\command"
            ) as key:
                command, _ = winreg.QueryValueEx(key, None)
            match = re.match(r'^\s*(?:"([^"]+)"|([^\s]+))', command)
            executable = (match.group(1) or match.group(2)) if match else ""
            if (
                Path(executable).name.lower().startswith("jt2go")
                and Path(executable).is_file()
            ):
                return executable
        except OSError:
            pass

    return None


def find_jt2go_app_id():
    """Find the AppUserModelID for a packaged JT2Go installation."""
    if os.name != "nt":
        return None

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$app = Get-StartApps | Where-Object { $_.Name -match 'JT2Go' } "
            "| Select-Object -First 1; if ($app) { $app.AppID }",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"Could not find the JT2Go app registration: {detail}")
    return next((line.strip() for line in result.stdout.splitlines() if line.strip()), None)


def activate_packaged_jt2go(app_id, file_path):
    """Activate the packaged JT2Go app and pass it the file to open."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    def guid(value):
        return GUID.from_buffer_copy(uuid.UUID(value).bytes_le)

    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(GUID),
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None

    initialized = ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    if initialized < 0:
        raise OSError(f"Could not initialize Windows app activation (HRESULT 0x{initialized & 0xFFFFFFFF:08X}).")

    instance = ctypes.c_void_p()
    try:
        result = ole32.CoCreateInstance(
            ctypes.byref(guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")),
            None,
            4,  # CLSCTX_LOCAL_SERVER
            ctypes.byref(guid("2E941141-7F97-4756-BA1D-9DECDE894A3D")),
            ctypes.byref(instance),
        )
        if result < 0:
            raise OSError(f"Could not create the Windows app activator (HRESULT 0x{result & 0xFFFFFFFF:08X}).")

        vtable = ctypes.cast(
            instance, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        ).contents
        activate = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        )(vtable[3])
        process_id = wintypes.DWORD()
        result = activate(
            instance,
            app_id,
            subprocess.list2cmdline([str(file_path)]),
            0,
            ctypes.byref(process_id),
        )
        if result < 0:
            raise OSError(f"JT2Go activation failed (HRESULT 0x{result & 0xFFFFFFFF:08X}).")
    finally:
        if instance:
            release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
            release(instance)
        ole32.CoUninitialize()


def file_digest(file) -> str:
    """SHA-256 of the uploaded file's contents plus the converter version."""
    h = hashlib.sha256()
    for chunk in iter(lambda: file.stream.read(1024 * 1024), b""):
        h.update(chunk)
    file.stream.seek(0)  # rewind so file.save() still works
    h.update(CONVERTER_VERSION.encode())
    return h.hexdigest()


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@app.route("/health")
def health():
    a3d, err = load_aspose()
    return jsonify(aspose_available=a3d is not None, converter_version=CONVERTER_VERSION, error=err)




@app.route("/probe", methods=["POST"])
def probe():
    """Plain-text report of the color data stored inside the JT file (no Aspose involved)."""
    file, bad = check_upload()
    if bad:
        return bad
    try:
        lines = probe_jt(file.read())
    except Exception as e:
        app.logger.exception("Probe failed")
        return Response(f"Probe failed: {type(e).__name__}: {e}", mimetype="text/plain", status=500)
    return Response("\n".join(lines), mimetype="text/plain")


@app.route("/inspect", methods=["POST"])
def inspect():
    """Upload a .jt and see which materials / colors Aspose reads from it."""
    file, bad = check_upload()
    if bad:
        return bad
    a3d, err = load_aspose()
    if a3d is None:
        return jsonify(error=err), 500

    src = UPLOADS / f"{uuid.uuid4().hex}.jt"
    file.save(src)
    try:
        scene = a3d.Scene.from_file(str(src))
        found = []

        def walk(node):
            for m in (node.materials or []):
                info = {"node": node.name, "material": type(m).__name__}
                for attr in ("diffuse_color", "albedo", "ambient_color"):
                    if hasattr(m, attr):
                        info[attr] = str(getattr(m, attr))
                found.append(info)
            for c in node.child_nodes:
                walk(c)

        walk(scene.root_node)
        return jsonify(material_count=len(found), materials=found[:50])
    except Exception as e:
        app.logger.exception("Inspect failed")
        return jsonify(error=str(e)), 500
    finally:
        src.unlink(missing_ok=True)


@app.route("/convert", methods=["POST"])
def convert():
    file, bad = check_upload()
    if bad:
        return bad

    fmt = (request.args.get("format") or request.form.get("format") or "glb").lower()
    if fmt not in ("glb", "gltf"):
        return jsonify(error="format must be 'glb' or 'gltf'."), 400

    job_id = uuid.uuid4().hex
    src = UPLOADS / f"{job_id}.jt"
    job_dir = CONVERTED / f"job_{job_id}"
    job_dir.mkdir()
    stem = Path(secure_filename(file.filename)).stem or "model"
    file.save(src)

    try:
        convert_jt(src, job_dir / f"model.{fmt}")
        files = sorted(p for p in job_dir.rglob("*") if p.is_file())

        buf = io.BytesIO()
        if len(files) == 1:
            # A single output file (always the case for .glb)
            buf.write(files[0].read_bytes())
            download_name, mimetype = f"{stem}.{fmt}", MIMETYPES[fmt]
        else:
            # .gltf with extra files (.bin, textures): bundle them together
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for p in files:
                    arcname = p.relative_to(job_dir).as_posix()
                    if arcname == f"model.{fmt}":
                        arcname = f"{stem}.{fmt}"
                    z.write(p, arcname)
            download_name, mimetype = f"{stem}_gltf.zip", MIMETYPES["zip"]
        buf.seek(0)
    except Exception as e:
        app.logger.exception("Conversion failed")
        return jsonify(error=f"Conversion failed: {e}"), 500
    finally:
        src.unlink(missing_ok=True)
        shutil.rmtree(job_dir, ignore_errors=True)

    return send_file(buf, mimetype=mimetype, as_attachment=True, download_name=download_name)


@app.route("/upload", methods=["POST"])
def upload():
    """Used by the web viewer page: converts to .glb (once per unique file) and returns a URL."""
    file, bad = check_upload()
    if bad:
        return bad

    digest = file_digest(file)
    dst = CONVERTED / f"{digest}.glb"

    # Same file uploaded before: return the existing result, no conversion
    if dst.exists() and dst.stat().st_size > 0:
        return jsonify(url=f"/models/{digest}.glb", cached=True)

    job_id = uuid.uuid4().hex
    src = UPLOADS / f"{job_id}.jt"
    tmp = CONVERTED / f"{digest}.{job_id}.tmp.glb"
    file.save(src)

    try:
        convert_jt(src, tmp)
        os.replace(tmp, dst)  # atomic: a half-written file is never served
    except Exception as e:
        app.logger.exception("Conversion failed")
        return jsonify(error=f"Conversion failed: {e}"), 500
    finally:
        src.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)

    return jsonify(url=f"/models/{digest}.glb", cached=False)

@app.route("/add-to-jt2go", methods=["POST"])
def add_to_jt2go():
    file, bad = check_upload()
    if bad:
        return bad
    try:
        executable = find_jt2go_executable()
        app_id = None if executable else find_jt2go_app_id()
    except Exception as e:
        app.logger.exception("Could not find JT2Go")
        return jsonify(error=f"Could not find JT2Go: {type(e).__name__}: {e}"), 500

    if not executable and not app_id:
        return jsonify(
            error=(
                "JT2Go was not found. Install Siemens JT2Go or set "
                "JT2GO_EXE to the full path of JT2Go.exe."
            )
        ), 503

    try:
        folder = UPLOADS / "jt2go" / uuid.uuid4().hex
        folder.mkdir(parents=True)
        dst = folder / secure_filename(file.filename)
        file.save(dst)
        if executable:
            subprocess.Popen([executable, str(dst)], cwd=str(Path(executable).parent))
        else:
            activate_packaged_jt2go(app_id, dst)
    except Exception as e:
        app.logger.exception("Add to JT2Go failed")
        return jsonify(error=f"Could not start JT2Go: {type(e).__name__}: {e}"), 500
    return jsonify(ok=True, path=str(dst))
@app.route("/models/<name>")
def models(name):
    return send_from_directory(CONVERTED, name, mimetype=MIMETYPES["glb"])


@app.route("/")
def index():
    return send_from_directory(BASE, "index.html")


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
