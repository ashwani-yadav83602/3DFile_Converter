"""Start the Flask application with Waitress in the current desktop session."""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from waitress import serve

from app import create_app
from app.config import HOST, PORT


if __name__ == "__main__":
    print(f"Starting JT converter at http://{HOST}:{PORT}", flush=True)
    try:
        serve(create_app(), host=HOST, port=PORT, threads=4)
    except OSError as error:
        raise SystemExit(
            f"Could not start the JT converter at {HOST}:{PORT}: {error}. "
            "Check whether another server is already using this address."
        ) from error
