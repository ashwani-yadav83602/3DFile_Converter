import threading
import time
import urllib.request

import webview
from waitress import serve

from app import create_app
from app.config import HOST, PORT

flask_app = create_app()


def run_server():
    serve(flask_app, host=HOST, port=PORT)


# def server_is_up():
#     try:
#         urllib.request.urlopen(f"http://{HOST}:{PORT}/", timeout=1)
#         return True
#     except Exception:
#         return False
import urllib.error
import urllib.request

def server_is_up():
    try:
        urllib.request.urlopen(f"http://{HOST}:{PORT}/health", timeout=1)
        return True
    except urllib.error.HTTPError:
        return True      # server chal raha hai, bas page ne error diya
    except Exception:
        return False     # server abhi start nahi hua


def wait_until_ready(timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server_is_up():
            return
        time.sleep(0.2)


if __name__ == "__main__":
    if not server_is_up():
        threading.Thread(target=run_server, daemon=True).start()
        wait_until_ready()
    webview.create_window("JT Viewer", f"http://{HOST}:{PORT}/", width=1280, height=800)
    webview.start()