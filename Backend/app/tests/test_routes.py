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
        self.assertIn(b">All Files<", page)
        self.assertIn(b">My Files<", page)
        self.assertIn(b">Upload File<", page)
        self.assertIn(b'data-view="mine"', page)
        self.assertIn(b'id="pageMount"', page)
        self.assertIn(b'<script type="module" src="/static/js/app.js"></script>', page)
        self.assertLess(len(page), 5000)

    def test_split_pages_and_assets_are_served(self):
        static_root = Path(__file__).parent.parent / "static"
        assets = [
            asset for asset in static_root.rglob("*")
            if asset.is_file() and asset.name != "index.html"
        ]
        for asset in assets:
            path = f"/static/{asset.relative_to(static_root).as_posix()}"
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                response.close()

        upload = self.client.get("/static/pages/upload/UploadPage.html")
        self.assertIn(b"Model preview", upload.data)
        self.assertIn(b"Download original .jt", upload.data)
        upload.close()

        files = self.client.get("/static/pages/files/FilesPage.html")
        self.assertIn(b'id="fileSearch"', files.data)
        self.assertIn(b'id="uploadedFilesTitle">All Files', files.data)
        self.assertIn(b'id="jt2goActionHeader"', files.data)
        files.close()

        viewer = self.client.get("/static/js/pages/upload/ModelViewer.js")
        self.assertIn(b"import(MODEL_VIEWER_URL)", viewer.data)
        viewer.close()

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
