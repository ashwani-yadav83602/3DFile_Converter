"""Health, frontend, and converted-model routes."""

from flask import Blueprint, current_app, jsonify, request, send_from_directory

from ..services.conversion import CONVERTER_VERSION, MIMETYPES, load_aspose

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def index():
    return send_from_directory(current_app.static_folder, "index.html")


@main_bp.get("/health")
def health():
    a3d, error = load_aspose()
    return jsonify(
        aspose_available=a3d is not None,
        converter_version=CONVERTER_VERSION,
        error=error,
    )


@main_bp.get("/models/<name>")
def models(name):
    return send_from_directory(
        current_app.config["CONVERTED_DIR"],
        name,
        mimetype=MIMETYPES["glb"],
        as_attachment=request.args.get("download") == "1",
    )
