"""Runtime configuration and paths for the local JT converter."""

import os
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = Path(os.environ.get("JT_UPLOADS_DIR", APP_DIR / "uploads"))
CONVERTED_DIR = Path(os.environ.get("JT_CONVERTED_DIR", APP_DIR / "converted"))
MAX_CONTENT_LENGTH = 200 * 1024 * 1024
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "5000"))
