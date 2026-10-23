from io import BytesIO
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from app import create_app


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(__file__).parent / "temp" / uuid4().hex
        self.app = create_app(
            {
                "TESTING": True,
                "UPLOADS_DIR": self.temp_dir / "uploads",
                "CONVERTED_DIR": self.temp_dir / "converted",
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_factory_registers_blueprints(self):
        self.assertEqual(set(self.app.blueprints), {"main", "conversion", "jt2go"})

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
        model = self.temp_dir / "converted" / name
        model.write_bytes(b"test model")
        self.addCleanup(model.unlink, missing_ok=True)

        response = self.client.get(f"/models/{name}?download=1")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["Content-Disposition"].startswith("attachment;"))
        response.close()
