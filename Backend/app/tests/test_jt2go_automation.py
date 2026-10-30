import tempfile
import unittest
import ctypes
from pathlib import Path
from unittest.mock import Mock, patch

from app.jt2go_watcher import should_intercept_insert
from app.services.jt2go import (
    INSERT_SHORTCUT,
    _enter_open_dialog_path,
    _find_dialog_controls,
    _trigger_insert_dialog,
    _wait_for_new_model_tab,
    _wait_for_open_dialog,
    add_file_to_jt2go_window,
    file_dialog_title_matches,
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
        open_button.wait.assert_called_once_with("enabled", timeout=2)
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
                existing_tabs={10: same_name},
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

    def test_file_dialog_title_matches_insert_file(self):
        self.assertTrue(file_dialog_title_matches("Insert File"))
        self.assertTrue(file_dialog_title_matches("Open"))
        self.assertFalse(file_dialog_title_matches("Save As"))

    def test_wait_for_open_dialog_accepts_insert_file_title(self):
        main_window = Mock()
        main_window.process_id.return_value = 42
        dialog = Mock()
        desktop = Mock()
        desktop.window.return_value = dialog
        desktop.windows.return_value = []
        fake_user32 = Mock()
        fake_user32.IsWindow.return_value = True
        fake_user32.IsWindowVisible.return_value = True

        with (
            patch(
                "app.services.jt2go._active_popup",
                return_value=(200, 42, "Insert File"),
            ),
            patch("pywinauto.Desktop", return_value=desktop),
            patch.object(ctypes, "WinDLL", return_value=fake_user32),
            patch("time.sleep"),
        ):
            found = _wait_for_open_dialog(main_window, timeout=1)

        self.assertIs(found, dialog)
        desktop.window.assert_called_once()

    def test_add_file_to_jt2go_window_uses_insert_dialog(self):
        window = Mock()
        dialog = Mock()
        dialog.handle = 321
        filename = Mock()
        open_button = Mock()

        with (
            patch("app.services.jt2go._force_window_to_foreground"),
            patch("app.services.jt2go._close_stray_dialog"),
            patch(
                "app.services.jt2go._trigger_insert_dialog",
                return_value=dialog,
            ) as trigger,
            patch(
                "app.services.jt2go._find_dialog_controls",
                return_value=(filename, open_button),
            ),
            patch("app.services.jt2go._enter_open_dialog_path") as enter,
            patch("app.services.jt2go._wait_for_open_dialog_close") as close_dialog,
            patch("app.services.jt2go.find_jt2go_window", return_value=window),
            patch("time.sleep"),
        ):
            add_file_to_jt2go_window(window, r"C:\uploads\part.jt")

        trigger.assert_called_once_with(window)
        enter.assert_called_once_with(filename, open_button, r"C:\uploads\part.jt")
        close_dialog.assert_called_once_with(321)

    def test_trigger_insert_dialog_sends_shortcut(self):
        window = Mock()
        dialog = Mock()
        with (
            patch("app.services.jt2go._force_window_to_foreground"),
            patch(
                "app.services.jt2go._wait_for_open_dialog",
                return_value=dialog,
            ),
            patch("time.sleep"),
        ):
            found = _trigger_insert_dialog(window, timeout=5)

        window.type_keys.assert_called_with(INSERT_SHORTCUT)
        self.assertIs(found, dialog)

    def test_find_dialog_controls_prefers_native_ids(self):
        filename = Mock()
        filename.exists.return_value = True
        open_button = Mock()
        open_button.exists.return_value = True
        dialog = Mock()
        dialog.child_window.side_effect = lambda **kwargs: (
            filename if kwargs.get("auto_id") == "3078" else open_button
        )

        found_filename, found_button = _find_dialog_controls(dialog)

        self.assertIs(found_filename, filename)
        self.assertIs(found_button, open_button)

    def test_watcher_skips_insert_while_busy_flag_exists(self):
        with patch("app.jt2go_watcher.jt2go.BUSY_FLAG") as flag:
            flag.exists.return_value = True
            self.assertFalse(should_intercept_insert("Insert File"))
            self.assertFalse(should_intercept_insert("Open"))

    def test_watcher_intercepts_user_insert_when_idle(self):
        with patch("app.jt2go_watcher.jt2go.BUSY_FLAG") as flag:
            flag.exists.return_value = False
            self.assertTrue(should_intercept_insert("Insert File"))
            self.assertTrue(should_intercept_insert("open"))
            self.assertFalse(should_intercept_insert("Save As"))
