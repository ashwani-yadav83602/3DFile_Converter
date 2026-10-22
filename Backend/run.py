"""Production WSGI entrypoint for the local Windows desktop server."""

from waitress import serve

try:
    from .config import HOST, PORT
    from .converter_server import app
except ImportError:
    from config import HOST, PORT
    from converter_server import app


if __name__ == "__main__":
    serve(app, host=HOST, port=PORT, threads=4)
