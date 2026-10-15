"""
JT converter server.

  GET  /health                      -> is Aspose.3D usable? (shows the real error if not)
  POST /convert?format=gltf|glb     -> multipart field "file" (.jt); returns the converted file
                                       (a .zip if the .gltf comes with extra files like .bin)
  POST /upload                      -> same conversion to .glb, returns {"url": ...} for the web viewer
  GET  /models/<name>               -> serves converted .glb files for the viewer
  GET  /                            -> serves index.html (the viewer page)

Run with the Python that has aspose-3d installed:
  .\\venv\\Scripts\\python.exe converter_server.py
"""
import io
import os
import shutil
import uuid
import zipfile
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

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

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB upload limit


@app.after_request
def add_cors(resp):
    # Only needed if another website calls this API. Example: set CORS_ORIGIN=http://localhost:3000
    origin = os.environ.get("CORS_ORIGIN")
    if origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
    return resp


def load_aspose():
    """Return (module, None) or (None, readable error)."""
    try:
        import aspose.threed as a3d
        return a3d, None
    except Exception as e:  # ImportError, missing DLLs, unsupported Python, ...
        return None, f"{type(e).__name__}: {e}"


def convert_jt(src: Path, dst: Path) -> None:
    """Convert a .jt file to dst (.glb or .gltf, chosen by dst's extension)."""
    a3d, err = load_aspose()
    if a3d is None:
        raise RuntimeError(f"Aspose.3D could not be loaded ({err})")

    # Aspose.3D is commercial; without a license it runs in evaluation mode.
    scene = a3d.Scene.from_file(str(src))
    scene.save(str(dst))

    if not dst.exists():
        raise RuntimeError("Conversion finished but no output file was produced.")


def check_upload():
    """Validate the uploaded file. Returns (file, error_response)."""
    file = request.files.get("file")
    if not file or not file.filename:
        return None, (jsonify(error="No file selected."), 400)
    if not file.filename.lower().endswith(".jt"):
        return None, (jsonify(error="Only .jt files are allowed."), 400)
    return file, None


@app.route("/health")
def health():
    a3d, err = load_aspose()
    return jsonify(aspose_available=a3d is not None, error=err)


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
    """Used by the web viewer page: converts to .glb and returns a URL to display it."""
    file, bad = check_upload()
    if bad:
        return bad

    job_id = uuid.uuid4().hex
    src = UPLOADS / f"{job_id}.jt"
    dst = CONVERTED / f"{job_id}.glb"
    file.save(src)

    try:
        convert_jt(src, dst)
    except Exception as e:
        app.logger.exception("Conversion failed")
        return jsonify(error=f"Conversion failed: {e}"), 500
    finally:
        src.unlink(missing_ok=True)

    return jsonify(url=f"/models/{job_id}.glb")


@app.route("/models/<name>")
def models(name):
    return send_from_directory(CONVERTED, name, mimetype=MIMETYPES["glb"])


@app.route("/")
def index():
    return send_from_directory(BASE, "index.html")


if __name__ == "__main__":
    app.run(debug=True)
