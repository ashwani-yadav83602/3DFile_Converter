"""API endpoints for storing JT files and registering their metadata."""

from flask import Blueprint, current_app, jsonify, request

from ..services.jt_file_uploads import (
    JTFileDatabaseError,
    JTFileValidationError,
    insert_jt_file_record,
    list_jt_file_records,
    save_jt_file,
)
from ..utils.uploads import check_upload

jt_files_bp = Blueprint("jt_files", __name__, url_prefix="/api/jt-files")
jt_file_list_bp = Blueprint("jt_file_list", __name__)


@jt_file_list_bp.get("/list")
def list_jt_files():
    try:
        files = list_jt_file_records()
    except JTFileDatabaseError:
        return jsonify(error="Could not load uploaded JT file information from MySQL."), 503
    return jsonify(files=files, count=len(files))

@jt_files_bp.post("/upload")
def upload_jt_file():
    upload, bad = check_upload()
    if bad:
        return bad

    try:
        filename, saved_path, size = save_jt_file(
            upload,
            current_app.config["SERVER_UPLOADS_DIR"],
            current_app.config["MAX_JT_FILE_SIZE"],
        )
    except JTFileValidationError as error:
        return jsonify(error=str(error)), 400

    try:
        record_id = insert_jt_file_record(
            filename=filename,
            file_location=saved_path,
            size=size,
        )
    except JTFileDatabaseError:
        try:
            saved_path.unlink(missing_ok=True)
        except OSError:
            current_app.logger.exception(
                "Could not remove JT upload after metadata registration failed"
            )
        return jsonify(
            error=(
                "The JT file was saved temporarily but could not be registered in "
                "MySQL. Check the database connection and schema, then try again."
            )
        ), 503

    return jsonify(
        status="success",
        id=record_id,
        filename=filename,
        file_size=size,
    ), 201
