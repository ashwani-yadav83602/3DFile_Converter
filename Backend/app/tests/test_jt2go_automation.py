import tempfile
import unittest
import ctypes
from pathlib import Path
from unittest.mock import Mock, patch

from app.services.jt2go import (
    _enter_open_dialog_path,
    _wait_for_new_model_tab,
    open_file_in_jt2go,
)


class JT2GoAutomationTests(unittest.TestCase):
    def test_open_dialog_path_is_submitted_through_native_dialog_command(self):
        path = Path(tempfile.gettempdir()) / "model with spaces.jt"
        filename = Mock()
        filename.handle = 456
        open_button = Mock()
        open_button.handle = 789
        fake_user32 = Mock()
        current_text = {"value": ""}

        def send_message(_handle, message, value, _detail):
            if message == 0x0102:
                if value == 8:
                    current_text["value"] = ""
                else:
                    current_text["value"] += chr(value)
            elif message == 0x00B1:
                current_text["value"] = ""
            elif message == 0x000D:
                buffer = ctypes.create_unicode_buffer(current_text["value"])
                ctypes.memmove(_detail, buffer, ctypes.sizeof(buffer))
                return len(current_text["value"])
            return 1

        fake_user32.SendMessageW.side_effect = send_message
        fake_user32.PostMessageW.return_value = True

        with patch.object(ctypes, "WinDLL", return_value=fake_user32):
            _enter_open_dialog_path(filename, open_button, path)

        first_message = fake_user32.SendMessageW.call_args_list[0].args
        self.assertEqual(first_message[0].value, 456)
        self.assertEqual(first_message[1:], (0x00B1, 0, -1))
        open_button.wait.assert_called_once_with("enabled", timeout=5)
        post_message_args = fake_user32.PostMessageW.call_args.args
        self.assertEqual(post_message_args[0].value, 789)
        self.assertEqual(post_message_args[1:], (0x00F5, 0, 0))

    def test_wait_for_new_model_tab_does_not_accept_previous_same_name_tab(self):
        main_window = Mock()
        same_name = "assembly.jt"
        with (
            patch(
                "app.services.jt2go._model_document_windows",
                side_effect=[
                    {10: same_name},
                    {10: same_name, 11: same_name},
                ],
            ),
            patch("time.sleep"),
        ):
            handle = _wait_for_new_model_tab(
                main_window,
                r"C:\uploads\assembly.jt",
                existing_handles={10},
                timeout=1,
            )

        self.assertEqual(handle, 11)

    def test_existing_jt2go_window_uses_open_instead_of_reactivation(self):
        window = Mock()
        with (
            patch("app.services.jt2go.find_jt2go_window", return_value=window),
            patch("app.services.jt2go.add_file_to_jt2go_window") as add_file,
            patch("app.services.jt2go.find_jt2go_app_id") as find_app,
            patch("app.services.jt2go.activate_packaged_jt2go") as activate,
        ):
            result = open_file_in_jt2go(r"C:\uploads\assembly.jt")

        self.assertTrue(result)
        add_file.assert_called_once_with(window, r"C:\uploads\assembly.jt")
        find_app.assert_not_called()
        activate.assert_not_called()
