from io import BytesIO
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from app import create_app


class RegisteredJT2GoTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(__file__).parent / "temp" / uuid4().hex
        self.upload_dir = self.temp_dir / "server_uploads"
        self.app = create_app(
            {
                "TESTING": True,
                "UPLOADS_DIR": self.temp_dir / "uploads",
                "CONVERTED_DIR": self.temp_dir / "converted",
                "SERVER_UPLOADS_DIR": self.upload_dir,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_opens_registered_file_from_server_uploads(self):
        jt_file = self.upload_dir / "assembly.jt"
        jt_file.write_bytes(b"JT")

        with (
            patch(
                "app.routes.jt_files.get_local_jt_file_path",
                return_value=str(jt_file),
            ),
            patch(
                "app.routes.jt_files.open_file_in_jt2go",
                return_value=True,
            ) as open_file,
        ):
            response = self.client.post("/api/jt-files/12/open-in-jt2go")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json,
            {"ok": True, "filename": "assembly.jt", "new_tab": True},
        )
        open_file.assert_called_once_with(jt_file.resolve())
        response.close()

    def test_existing_upload_action_still_opens_selected_file(self):
        window = object()
        with (
            patch(
                "app.routes.jt2go.find_jt2go_window",
                return_value=window,
            ),
            patch("app.routes.jt2go.add_file_to_jt2go_window") as open_file,
            patch("app.routes.jt2go.find_jt2go_app_id") as find_app,
        ):
            response = self.client.post(
                "/add-to-jt2go",
                data={"file": (BytesIO(b"JT"), "selected.jt")},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["new_tab"], True)
        open_file.assert_called_once()
        self.assertIs(open_file.call_args.args[0], window)
        find_app.assert_not_called()
        self.assertTrue(Path(response.json["path"]).is_file())
        response.close()

    def test_rejects_a_path_outside_server_uploads(self):
        outside_file = self.temp_dir / "outside.jt"
        outside_file.write_bytes(b"JT")

        with (
            patch(
                "app.routes.jt_files.get_local_jt_file_path",
                return_value=str(outside_file),
            ),
            patch("app.routes.jt_files.open_file_in_jt2go") as open_file,
        ):
            response = self.client.post("/api/jt-files/12/open-in-jt2go")

        self.assertEqual(response.status_code, 404)
        open_file.assert_not_called()
        response.close()

    def test_reports_missing_records(self):
        with patch(
            "app.routes.jt_files.get_local_jt_file_path",
            return_value=None,
        ):
            response = self.client.post("/api/jt-files/999/open-in-jt2go")

        self.assertEqual(response.status_code, 404)
        response.close()

    def test_reports_when_jt2go_is_not_installed(self):
        jt_file = self.upload_dir / "assembly.jt"
        jt_file.write_bytes(b"JT")

        with (
            patch(
                "app.routes.jt_files.get_local_jt_file_path",
                return_value=str(jt_file),
            ),
            patch(
                "app.routes.jt_files.open_file_in_jt2go",
                return_value=False,
            ),
        ):
            response = self.client.post("/api/jt-files/12/open-in-jt2go")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["error"], "JT2Go was not found.")
        response.close()
