"""Start the Flask application with Waitress in the current desktop session."""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from waitress import serve

from app import create_app
from app.config import HOST, PORT
from app.services.database import DatabaseStartupError, verify_database_connection


if __name__ == "__main__":
    app = create_app()
    print("Checking MySQL connection...", flush=True)
    try:
        verify_database_connection(app.config)
    except DatabaseStartupError as error:
        raise SystemExit(
            f"JT Studio was not started because the database is unavailable. {error}"
        ) from error

    print("MySQL connection successful.", flush=True)
    print(f"Starting JT converter at http://{HOST}:{PORT}", flush=True)
    try:
        serve(app, host=HOST, port=PORT, threads=4)
    except OSError as error:
        raise SystemExit(
            f"Could not start the JT converter at {HOST}:{PORT}: {error}. "
            "Check whether another server is already using this address."
        ) from error
