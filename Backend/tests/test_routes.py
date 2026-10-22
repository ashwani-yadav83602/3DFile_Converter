from io import BytesIO
import unittest
from uuid import uuid4

try:
    from Backend.converter_server import CONVERTED, app
except ModuleNotFoundError:
    from converter_server import CONVERTED, app


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_homepage_serves_frontend(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Please select a .jt file", response.data)
        response.close()

    def test_invalid_upload_returns_json(self):
        response = self.client.post(
            "/upload",
            data={"file": (BytesIO(b"not a JT file"), "model.txt")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["error"], "Only .jt files are allowed.")
        response.close()

    def test_model_download_is_an_attachment(self):
        name = f"test-{uuid4().hex}.glb"
        model = CONVERTED / name
        model.write_bytes(b"test model")
        self.addCleanup(model.unlink, missing_ok=True)

        response = self.client.get(f"/models/{name}?download=1")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["Content-Disposition"].startswith("attachment;"))
        response.close()
