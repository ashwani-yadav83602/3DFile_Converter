"""Consistent JSON error handlers for API and page requests."""

from flask import current_app, jsonify
from werkzeug.exceptions import HTTPException


def register_error_handlers(app):
    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        current_app.logger.exception("Unhandled request error")
        return jsonify(error=f"{type(error).__name__}: {error}"), 500
