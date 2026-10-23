from io import BytesIO
import shutil
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from app import create_app


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(__file__).parent / "temp" / uuid4().hex
        self.app = create_app(
            {
                "TESTING": True,
                "UPLOADS_DIR": self.temp_dir / "uploads",
                "CONVERTED_DIR": self.temp_dir / "converted",
                "SERVER_UPLOADS_DIR": self.temp_dir / "server_uploads",
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_factory_registers_blueprints(self):
        self.assertEqual(
            set(self.app.blueprints),
            {"main", "conversion", "jt2go", "jt_files", "jt_file_list"},
        )

    def test_homepage_serves_frontend(self):
        response = self.client.get("/")
        page = response.data
        response.close()

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Model preview", page)
        self.assertIn(b"Download original .jt", page)
        self.assertIn(b"Upload to server", page)
        self.assertIn(b'id="fileSearch"', page)
        self.assertIn(b"Uploaded JT files", page)
        self.assertIn(b"id=\"refreshFilesBtn\"", page)

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

    def test_existing_preview_upload_route_keeps_its_response_shape(self):
        def create_glb(source, destination):
            destination.write_bytes(b"mock GLB")

        with (
            patch("app.routes.conversion.file_digest", return_value="a" * 64),
            patch("app.routes.conversion.convert_jt", side_effect=create_glb),
        ):
            response = self.client.post(
                "/upload",
                data={"file": (BytesIO(b"valid JT test bytes"), "model.jt")},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json,
            {"url": f"/models/{'a' * 64}.glb", "cached": False},
        )
        response.close()
