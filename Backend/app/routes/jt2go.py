"""Routes for opening uploaded JT models in the interactive JT2Go desktop app."""

import uuid

from flask import Blueprint, current_app, jsonify
from werkzeug.utils import secure_filename

from ..services.jt2go import (
    JT2GO_LOCK,
    activate_packaged_jt2go,
    add_file_to_jt2go_window,
    find_jt2go_app_id,
    find_jt2go_window,
)
from ..utils.uploads import check_upload

jt2go_bp = Blueprint("jt2go", __name__)


@jt2go_bp.post("/add-to-jt2go")
def add_to_jt2go():
    file, bad = check_upload()
    if bad:
        return bad

    with JT2GO_LOCK:
        folder = current_app.config["UPLOADS_DIR"] / "jt2go" / uuid.uuid4().hex
        folder.mkdir(parents=True)
        destination = folder / secure_filename(file.filename)
        file.save(destination)

        try:
            window = find_jt2go_window()
            if window:
                add_file_to_jt2go_window(window, destination)
            else:
                app_id = find_jt2go_app_id()
                if not app_id:
                    return jsonify(error="JT2Go was not found."), 503
                activate_packaged_jt2go(app_id, destination)
            return jsonify(ok=True, path=str(destination), new_tab=True)
        except Exception as error:
            current_app.logger.exception("Add to JT2Go failed")
            return jsonify(
                error=f"Could not add file to JT2Go: {type(error).__name__}: {error}"
            ), 500
