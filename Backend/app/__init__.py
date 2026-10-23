"""Flask application factory."""

import os
from pathlib import Path

from flask import Flask

from .config import CONVERTED_DIR, MAX_CONTENT_LENGTH, UPLOADS_DIR

from .routes.conversion import conversion_bp
from .routes.jt2go import jt2go_bp
from .routes.main import main_bp
from .utils.errors import register_error_handlers


def create_app(test_config=None):
    app = Flask(__name__, static_folder="static")
    app.config.from_mapping(
        MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
        UPLOADS_DIR=UPLOADS_DIR,
        CONVERTED_DIR=CONVERTED_DIR,
    )
    if test_config is not None:
        app.config.update(test_config)

    for key in ("UPLOADS_DIR", "CONVERTED_DIR"):
        directory = Path(app.config[key])
        directory.mkdir(parents=True, exist_ok=True)
        app.config[key] = directory

    register_error_handlers(app)
    app.register_blueprint(main_bp)
    app.register_blueprint(conversion_bp)
    app.register_blueprint(jt2go_bp)

    @app.after_request
    def add_cors(response):
        origin = os.environ.get("CORS_ORIGIN")
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
        return response

    return app
