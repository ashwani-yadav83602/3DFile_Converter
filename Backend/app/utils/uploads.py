"""Validation helpers for uploaded JT files."""

from flask import jsonify, request


def check_upload():
    """Return the uploaded JT file or its JSON error response."""
    file = request.files.get("file")
    if not file or not file.filename:
        return None, (jsonify(error="No file selected."), 400)
    if not file.filename.lower().endswith(".jt"):
        return None, (jsonify(error="Only .jt files are allowed."), 400)
    return file, None
