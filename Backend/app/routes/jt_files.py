
"""API endpoints for storing JT files and registering their metadata."""

from pathlib import Path

from flask import Blueprint, current_app, jsonify, send_file

from ..services.jt_file_uploads import (
    JTFileDatabaseError,
    JTFileValidationError,
    get_local_jt_file_path,
    insert_jt_file_record,
    list_jt_file_records,
    save_jt_file,
)

from ..services.jt2go import open_file_in_jt2go
from ..utils.uploads import check_upload


jt_files_bp = Blueprint(
    "jt_files",
    __name__,
    url_prefix="/api/jt-files"
)

jt_file_list_bp = Blueprint(
    "jt_file_list",
    __name__
)


@jt_file_list_bp.get("/list")
def list_jt_files():
    try:
        files = list_jt_file_records()

    except JTFileDatabaseError:
        return jsonify(
            error="Could not load uploaded JT file information from MySQL."
        ), 503

    return jsonify(
        files=files,
        count=len(files)
    )


# ================= DOWNLOAD JT FILE =================

@jt_files_bp.get("/<int:file_id>/download")
def download_jt_file(file_id):

    try:
        stored_path = get_local_jt_file_path(file_id)

    except JTFileDatabaseError:
        return jsonify(
            error="Could not load the JT file information from MySQL."
        ), 503

    if not stored_path:
        return jsonify(
            error="File record was not found."
        ), 404

    try:
        upload_root = Path(
            current_app.config["SERVER_UPLOADS_DIR"]
        ).resolve()

        file_path = Path(stored_path).resolve(strict=True)

        # Allow files only inside ServerUploads
        file_path.relative_to(upload_root)

    except (OSError, RuntimeError, TypeError, ValueError):
        return jsonify(
            error="The file is missing from the server uploads folder."
        ), 404

    if not file_path.is_file():
        return jsonify(
            error="The stored record is not an available file."
        ), 404

    # Download debugging logs
    print(f"[DOWNLOAD] File ID: {file_id}", flush=True)
    print(f"[DOWNLOAD] File Path: {file_path}", flush=True)
    print(f"[DOWNLOAD] File Exists: {file_path.exists()}", flush=True)
    print(f"[DOWNLOAD] File Size: {file_path.stat().st_size} bytes", flush=True)

    return send_file(
        file_path,
        as_attachment=True,
        download_name=file_path.name
    )


# ================= UPLOAD JT FILE =================

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


# ================= OPEN IN JT2GO =================

@jt_files_bp.post("/<int:file_id>/open-in-jt2go")
def open_registered_jt_file(file_id):

    print(
        f"Request to open registered JT file with ID: {file_id}",
        flush=True
    )

    try:
        stored_path = get_local_jt_file_path(file_id)

    except JTFileDatabaseError:
        return jsonify(
            error="Could not load the JT file information from MySQL."
        ), 503

    if not stored_path:
        return jsonify(
            error="My Files record was not found."
        ), 404

    try:
        upload_root = Path(
            current_app.config["SERVER_UPLOADS_DIR"]
        ).resolve()

        file_path = Path(stored_path).resolve(strict=True)
        file_path.relative_to(upload_root)

    except (OSError, RuntimeError, TypeError, ValueError):
        return jsonify(
            error="The JT file is missing from the server uploads folder."
        ), 404

    if not file_path.is_file() or file_path.suffix.lower() != ".jt":
        return jsonify(
            error="The stored record is not an available JT file."
        ), 404

    try:
        if not open_file_in_jt2go(file_path):
            return jsonify(
                error="JT2Go was not found."
            ), 503

        return jsonify(
            ok=True,
            filename=file_path.name,
            new_tab=True
        )

    except Exception as error:
        print(
            f"Error occurred while opening JT file in JT2Go: "
            f"{type(error).__name__}: {error}",
            flush=True
        )

        current_app.logger.exception(
            "Open registered JT file in JT2Go failed"
        )

        return jsonify(
            error=(
                f"Could not open the JT file in JT2Go: "
                f"{type(error).__name__}: {error}"
            )
        ), 500
