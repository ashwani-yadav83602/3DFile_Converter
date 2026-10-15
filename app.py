import os
import subprocess
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

BASE = Path(__file__).parent
UPLOADS = BASE / "uploads"
CONVERTED = BASE / "converted"
UPLOADS.mkdir(exist_ok=True)
CONVERTED.mkdir(exist_ok=True)

# Optional: path to a command-line converter (e.g. CAD Exchanger's ExchangerConv).
# Only used if Aspose.3D is not installed.
CLI_CONVERTER = os.environ.get("JT_CONVERTER", "")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB upload limit


def convert_with_aspose(src: Path, dst: Path) -> None:
    # pip install aspose-3d
    # Aspose.3D is commercial: without a license it runs in evaluation mode
    # (watermark / limits). See Aspose's docs for applying a license.
    import aspose.threed as a3d

    scene = a3d.Scene.from_file(str(src))
    scene.save(str(dst))  # format is chosen from the .glb extension


def convert_with_cli(src: Path, dst: Path) -> None:
    try:
        result = subprocess.run(
            [CLI_CONVERTER, "-i", str(src), "-e", str(dst)],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        raise RuntimeError(f"Converter not found at '{CLI_CONVERTER}'.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Conversion timed out.")
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Conversion failed.").strip())


def convert_jt_to_glb(src: Path, dst: Path) -> None:
    """Convert with Aspose.3D if installed, otherwise with the CLI converter."""
    try:
        import aspose.threed  # noqa: F401
        has_aspose = True
    except ImportError:
        has_aspose = False

    if has_aspose:
        convert_with_aspose(src, dst)
    elif CLI_CONVERTER:
        convert_with_cli(src, dst)
    else:
        raise RuntimeError(
            "No JT converter available. Run 'pip install aspose-3d' "
            "or set JT_CONVERTER to a command-line converter."
        )

    if not dst.exists():
        raise RuntimeError("Conversion finished but no .glb file was produced.")


@app.route("/")
def index():
    return send_from_directory(BASE, "index.html")


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(error="No file selected."), 400

    if not file.filename.lower().endswith(".jt"):
        return jsonify(error="Only .jt files are allowed."), 400

    job_id = uuid.uuid4().hex
    src = UPLOADS / f"{job_id}.jt"
    dst = CONVERTED / f"{job_id}.glb"
    file.save(src)

    try:
        convert_jt_to_glb(src, dst)
    except Exception as e:  # report any converter failure to the page
        app.logger.exception("Conversion failed")
        return jsonify(error=f"Conversion failed: {e}"), 500
    finally:
        src.unlink(missing_ok=True)

    return jsonify(url=f"/models/{job_id}.glb")


@app.route("/models/<name>")
def models(name):
    return send_from_directory(CONVERTED, name, mimetype="model/gltf-binary")


if __name__ == "__main__":
    app.run(debug=True)
