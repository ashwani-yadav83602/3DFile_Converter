"""Windows UI Automation helpers for opening models in Siemens JT2Go."""

import os
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
import tempfile
import ctypes

INSERT_SHORTCUT = "^+i"   # pywinauto notation for Ctrl+Shift+I, must match step 1
DIALOG_TITLES = ("open", "open file", "insert file", "insert")
BUSY_FLAG = Path(tempfile.gettempdir()) / "jt2go_busy.flag"   # tells the watcher "this is my own automation"

JT2GO_LOCK = threading.Lock()


@contextmanager
def jt2go_automation():
    """Hold the in-process lock and the cross-process busy flag while driving JT2Go."""
    with JT2GO_LOCK:
        BUSY_FLAG.write_text("1")
        try:
            yield
        finally:
            BUSY_FLAG.unlink(missing_ok=True)


def open_file_in_jt2go(file_path):
    """Insert a JT file into the current JT2Go session (opens JT2Go if needed)."""
    print(f"Attempting to open JT file in JT2Go: {file_path}", flush=True)
    with jt2go_automation():
        window = find_jt2go_window()
        if window:
            add_file_to_jt2go_window(window, file_path)
            return True

        app_id = find_jt2go_app_id()
        if not app_id:
            return False
        activate_packaged_jt2go(app_id, file_path)
        print("Starting JT2Go...")
        return True


def find_jt2go_app_id():
    """Find the AppUserModelID for a packaged JT2Go installation."""
    if os.name != "nt":
        return None

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$app = Get-StartApps | Where-Object { $_.Name -match 'JT2Go' } "
            "| Select-Object -First 1; if ($app) { $app.AppID }",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"Could not find the JT2Go app registration: {detail}")
    return next((line.strip() for line in result.stdout.splitlines() if line.strip()), None)


def activate_packaged_jt2go(app_id, file_path):
    """Activate the packaged JT2Go app and pass it the file to open."""
    # import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    def guid(value):
        return GUID.from_buffer_copy(uuid.UUID(value).bytes_le)

    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(GUID),
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None

    initialized = ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    owns_com_initialization = initialized >= 0
    if initialized < 0 and initialized & 0xFFFFFFFF != 0x80010106:  # RPC_E_CHANGED_MODE
        raise OSError(f"Could not initialize Windows app activation (HRESULT 0x{initialized & 0xFFFFFFFF:08X}).")

    instance = ctypes.c_void_p()
    try:
        result = ole32.CoCreateInstance(
            ctypes.byref(guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")),
            None,
            4,  # CLSCTX_LOCAL_SERVER
            ctypes.byref(guid("2E941141-7F97-4756-BA1D-9DECDE894A3D")),
            ctypes.byref(instance),
        )
        if result < 0:
            raise OSError(f"Could not create the Windows app activator (HRESULT 0x{result & 0xFFFFFFFF:08X}).")

        vtable = ctypes.cast(
            instance, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        ).contents
        activate = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        )(vtable[3])
        process_id = wintypes.DWORD()
        result = activate(
            instance,
            app_id,
            subprocess.list2cmdline([str(file_path)]),
            0,
            ctypes.byref(process_id),
        )
        if result < 0:
            raise OSError(f"JT2Go activation failed (HRESULT 0x{result & 0xFFFFFFFF:08X}).")
    finally:
        if instance:
            release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
            release(instance)
        if owns_com_initialization:
            ole32.CoUninitialize()


def _process_image_path(process_id):
    """Return the executable path for a Windows process, or None if it is inaccessible."""
    if os.name != "nt":
        return None

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    process = kernel32.OpenProcess(0x1000, False, process_id)
    if not process:
        return None
    try:
        image_path = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(image_path))
        if kernel32.QueryFullProcessImageNameW(process, 0, image_path, ctypes.byref(size)):
            return image_path.value
        return None
    finally:
        kernel32.CloseHandle(process)


def find_jt2go_window():
    """Return JT2Go's main UIA window when the application is already open."""
    if os.name != "nt":
        return None

    from pywinauto import Desktop

    desktop = Desktop(backend="uia")
    process_paths = {}
    candidates = []
    for window in desktop.windows():
        if window.element_info.class_name == "#32770":
            continue
        process_id = window.process_id()
        if process_id not in process_paths:
            process_paths[process_id] = _process_image_path(process_id)
        image_path = process_paths[process_id]
        if image_path and "jt2go" in image_path.lower():
            candidates.append(window)

    selected = next(
        (window for window in candidates if "jt2go" in window.window_text().lower()),
        candidates[0] if candidates else None,
    )
    return desktop.window(handle=selected.handle) if selected else None


def _active_popup(main_window):
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetWindow.restype = wintypes.HWND
    handle = user32.GetWindow(main_window.handle, 6)  # GW_ENABLEDPOPUP
    if not handle or handle == main_window.handle:
        return None

    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    )
    title = ctypes.create_unicode_buffer(512)
    process_id = wintypes.DWORD()
    user32.GetWindowTextW(handle, title, len(title))
    user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
    return handle, process_id.value, title.value


# def _wait_for_open_dialog(main_window, timeout=15):
#     """Wait for JT2Go's modal Open dialog, including owned popup windows."""
#     import ctypes
#     from ctypes import wintypes
#     from pywinauto import Desktop
#     print("_wait_for_open_dialog...")
#     user32 = ctypes.WinDLL("user32", use_last_error=True)
#     user32.IsWindow.argtypes = (wintypes.HWND,)
#     user32.IsWindow.restype = wintypes.BOOL
#     user32.IsWindowVisible.argtypes = (wintypes.HWND,)
#     user32.IsWindowVisible.restype = wintypes.BOOL
#     desktop = Desktop(backend="uia")
#     deadline = time.monotonic() + timeout
#     while time.monotonic() < deadline:
#         popup = _active_popup(main_window)
#         if (
#             popup
#             and popup[1] == main_window.process_id()
#             and popup[2].strip().lower() == "open"
#             and user32.IsWindow(popup[0])
#             and user32.IsWindowVisible(popup[0])
#         ):
#             return desktop.window(handle=popup[0])

#         for window in desktop.windows():
#             if (
#                 window.process_id() == main_window.process_id()
#                 and window.element_info.class_name == "#32770"
#                 and window.window_text().strip().lower() == "open"
#                 and window.is_visible()
#             ):
#                 return window
#         time.sleep(0.2)
#     raise TimeoutError("JT2Go's Open file dialog did not appear.")
def file_dialog_title_matches(title):
    """True for JT2Go Open / Insert File dialog titles."""
    return (title or "").strip().lower() in DIALOG_TITLES


def _wait_for_open_dialog(main_window, timeout=15):
    """Wait for JT2Go's modal Open or Insert File dialog."""
    import ctypes
    from ctypes import wintypes
    from pywinauto import Desktop

    print("_wait_for_open_dialog...")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindow.argtypes = (wintypes.HWND,)
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL
    desktop = Desktop(backend="uia")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        popup = _active_popup(main_window)
        if (
            popup
            and popup[1] == main_window.process_id()
            and file_dialog_title_matches(popup[2])
            and user32.IsWindow(popup[0])
            and user32.IsWindowVisible(popup[0])
        ):
            return desktop.window(handle=popup[0])

        for window in desktop.windows():
            if (
                window.process_id() == main_window.process_id()
                and window.element_info.class_name == "#32770"
                and file_dialog_title_matches(window.window_text())
                and window.is_visible()
            ):
                return window

        try:
            for window in desktop.windows(process=main_window.process_id(), top_level_only=False):
                if file_dialog_title_matches(window.window_text()) and window.is_visible():
                    return window
        except Exception:
            pass

        time.sleep(0.2)
    raise TimeoutError("JT2Go's Insert/Open file dialog did not appear.")

def _model_document_windows(main_window):
    from pywinauto import Desktop

    process_id = main_window.process_id()
    documents = {}
    print("_model_document_windows...")
    for window in Desktop(backend="uia").windows():
        try:
            if (
                window.process_id() != process_id
                or window.element_info.class_name == "#32770"
            ):
                continue
            title = window.window_text().strip()
            if title.lower().endswith(".jt"):
                documents[window.handle] = title
            for child in window.descendants(control_type="Window"):
                title = child.window_text().strip()
                if title.lower().endswith(".jt"):
                    documents[child.handle] = title
        except Exception:
            continue
    return documents

def _wait_for_new_model_tab(main_window, file_path, existing_tabs=None, timeout=60):
    """Wait until JT2Go shows the requested file. Success also if it was already open."""
    from pathlib import Path

    expected_title = Path(file_path).name.casefold()
    existing_tabs = dict(existing_tabs or {})
    existing_handles = set(existing_tabs)
    deadline = time.monotonic() + timeout
    last_uia_error = None
    print("_wait_for_new_model_tab...")
    while time.monotonic() < deadline:
        try:
            for handle, title in _model_document_windows(main_window).items():
                if (
                    handle not in existing_handles
                    and title.strip().casefold() == expected_title
                ):
                    return handle
            last_uia_error = None
        except Exception as error:  # UIA can fail briefly while JT2Go updates
            last_uia_error = error
        time.sleep(0.3)

    # No new tab appeared, but the same file was already open: JT2Go switched to it.
    for handle, title in existing_tabs.items():
        if title.strip().casefold() == expected_title:
            print("File was already open in JT2Go; treating as success.")
            return handle

    message = (
        f"JT2Go did not display {Path(file_path).name!r} "
        f"within {timeout} seconds."
    )
    if last_uia_error:
        message += f" Last UI Automation error: {last_uia_error}"
    raise TimeoutError(message)


def _force_window_to_foreground(window, timeout=5):
    """Restore and activate a JT2Go top-level window."""
    import os
    import time
    import ctypes
    from ctypes import wintypes
    from pywinauto import Desktop

    if os.name != "nt":
        return False

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.AttachThreadInput.argtypes = [
        wintypes.DWORD, wintypes.DWORD, wintypes.BOOL
    ]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.SetFocus.argtypes = [wintypes.HWND]
    user32.SetFocus.restype = wintypes.HWND

    desktop = Desktop(backend="uia")
    try:
        pid = window.process_id()
        window_handle = window.handle
    except Exception:
        return False
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        candidates = []

        # Collect top-level windows from the JT2Go process.
        for item in desktop.windows():
            try:
                if item.process_id() != pid:
                    continue
                if not user32.IsWindow(item.handle):
                    continue
                if not user32.IsWindowVisible(item.handle):
                    continue

                title = item.window_text().strip()
                if title and title.lower() != "open":
                    candidates.append(item)
            except Exception:
                continue

        # Prefer the supplied window if it still exists.
        candidates.sort(
            key=lambda item: item.handle != window.handle
        )

        for item in candidates:
            hwnd = wintypes.HWND(item.handle)

            try:
                # Restore a minimized window.
                user32.ShowWindow(hwnd, 9)

                # First try pywinauto's normal activation.
                try:
                    item.set_focus()
                except Exception:
                    pass

                if user32.GetForegroundWindow() == hwnd:
                    return True

                # Retry with the foreground thread attached.
                foreground = user32.GetForegroundWindow()
                foreground_tid = (
                    user32.GetWindowThreadProcessId(foreground, None)
                    if foreground else 0
                )
                target_tid = user32.GetWindowThreadProcessId(
                    hwnd, None
                )
                current_tid = kernel32.GetCurrentThreadId()

                attached = []

                for tid in {foreground_tid, target_tid}:
                    if tid and tid != current_tid:
                        if user32.AttachThreadInput(
                            current_tid, tid, True
                        ):
                            attached.append(tid)

                try:
                    user32.BringWindowToTop(hwnd)
                    user32.SetForegroundWindow(hwnd)

                    try:
                        user32.SetFocus(hwnd)
                    except Exception:
                        pass

                    user32.SetForegroundWindow(hwnd)
                finally:
                    for tid in reversed(attached):
                        user32.AttachThreadInput(
                            current_tid, tid, False
                        )

                time.sleep(0.2)

                if user32.GetForegroundWindow() == hwnd:
                    return True

            except Exception:
                continue

        time.sleep(0.2)

    return False

def _enter_open_dialog_path(filename, open_button, file_path):
    """Type the filename into the native edit control and submit it."""
    import ctypes
    import os
    import time
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendMessageW.argtypes = (
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.PostMessageW.argtypes = (
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )
    user32.PostMessageW.restype = wintypes.BOOL
    user32.IsWindow.argtypes = (wintypes.HWND,)
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL

    filename_handle = wintypes.HWND(filename.handle)
    button_handle = wintypes.HWND(open_button.handle)

    user32.SendMessageW(filename_handle, 0x00B1, 0, -1)  # EM_SETSEL
    user32.SendMessageW(filename_handle, 0x0102, 8, 0)  # WM_CHAR: backspace
    encoded_path = str(file_path).encode("utf-16-le")
    for index in range(0, len(encoded_path), 2):
        character = int.from_bytes(encoded_path[index:index + 2], "little")
        user32.SendMessageW(filename_handle, 0x0102, character, 1)

    entered = ctypes.create_unicode_buffer(32768)
    if not user32.SendMessageW(
        filename_handle,
        0x000D,
        len(entered),
        ctypes.cast(entered, ctypes.c_void_p).value,
    ):  # WM_GETTEXT
        raise RuntimeError(
            "Could not verify the filename entered in JT2Go's Open dialog."
        )

    target_path = os.path.normcase(os.path.normpath(os.path.abspath(str(file_path))))
    actual_path = os.path.normcase(os.path.normpath(entered.value))
    if actual_path != target_path:
        raise RuntimeError(
            "JT2Go's Open dialog did not accept the complete file path."
        )

    try:
        open_button.wait("enabled", timeout=2)
    except Exception:
        pass  # button state is unreliable after raw WM_CHAR input; submit anyway

    if not user32.PostMessageW(button_handle, 0x00F5, 0, 0):  # BM_CLICK
        raise OSError("Could not submit the JT2Go Open dialog.")

    # If the dialog is still open after a moment, press Enter in the filename box
    time.sleep(1.5)
    if user32.IsWindow(button_handle) and user32.IsWindowVisible(button_handle):
        user32.PostMessageW(filename_handle, 0x0100, 0x0D, 0)  # WM_KEYDOWN, Enter
        user32.PostMessageW(filename_handle, 0x0101, 0x0D, 0)  # WM_KEYUP, Enter

def _wait_for_open_dialog_close(dialog_handle, timeout=15):
    """Wait for JT2Go to dismiss its native Open dialog after submission."""
    import ctypes
    import time
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindow.argtypes = (wintypes.HWND,)
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL
    handle = wintypes.HWND(int(dialog_handle))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not user32.IsWindow(handle) or not user32.IsWindowVisible(handle):
            return
        time.sleep(0.2)
    raise TimeoutError(
        "JT2Go's Open dialog did not close after submitting the file."
    )

def add_file_to_jt2go_window(window, file_path):
    """Open a JT file in JT2Go and bring the main window to the foreground."""
    if window is None:
        raise RuntimeError("JT2Go is not open (no JT2Go window found).")

    import time
    from pywinauto import Desktop

    desktop = Desktop(backend="uia")

    # Restore and activate JT2Go before interacting with it.
    _force_window_to_foreground(window)
    time.sleep(0.2)

    # Close a leftover Open dialog from an earlier failed attempt.
    try:
        stray = _active_popup(window)
        if (
            stray
            and stray[1] == window.process_id()
            and stray[2].strip().lower() in ("open", "open file")
        ):
            desktop.window(handle=stray[0]).type_keys("{ESC}")
            time.sleep(0.5)
    except Exception:
        pass

    existing_tabs = _model_document_windows(window)

    # Open the file dialog.
    application_menu = window.child_window(
        title="Application menu",
        control_type="Button",
    )

    if application_menu.exists(timeout=1):
        try:
            application_menu.invoke()
        except Exception:
            application_menu.click_input()  # fall back to a real mouse click

        open_item = window.child_window(
            title_re=r"Open\.\..*",
            control_type="MenuItem",
            found_index=0,
        )
        open_item.wait("visible", timeout=5)
        open_item.click_input()
    else:
        window.menu_select("File->Open...")

    # Wait for the Open dialog and activate it.
    found = _wait_for_open_dialog(window)
    dialog_handle = found.handle  # read once, while the dialog still exists
    dialog = desktop.window(handle=dialog_handle)
    _force_window_to_foreground(dialog)
    time.sleep(0.2)

    # Locate the filename input.
    filename = dialog.child_window(auto_id="3078", control_type="Edit")
    if not filename.exists(timeout=1):
        edits = dialog.descendants(control_type="Edit")
        filename = edits[0] if edits else None

    if filename is None:
        raise RuntimeError("Could not find the filename field in JT2Go's Open dialog.")

    open_button = dialog.child_window(auto_id="1", control_type="Button")
    if not open_button.exists(timeout=1):
        raise RuntimeError("Could not find the Open button in JT2Go's file dialog.")

    _enter_open_dialog_path(filename, open_button, file_path)
    _wait_for_open_dialog_close(dialog_handle)

    # Wait until the new model tab appears (or the file was already open).
    _wait_for_new_model_tab(window, file_path, existing_tabs, timeout=60)

    # Reactivate JT2Go after the model finishes loading.
    time.sleep(0.5)
    try:
        fresh = find_jt2go_window()  # look the window up again; its title changed
        if fresh is not None:
            try:
                fresh.restore()
            except Exception:
                pass
            if not _force_window_to_foreground(fresh, timeout=3):
                print(
                    "Warning: JT2Go opened the model, but Windows did not "
                    "allow its main window to become the foreground window."
                )
    except Exception as error:
        print(f"Could not bring JT2Go to the foreground (file is open): {error}")
        
def _close_stray_dialog(window):
    """Close an Insert/Open dialog the user left open, because it blocks everything else."""
    from pywinauto import Desktop
    for _ in range(3):
        stray = _active_popup(window)
        if not (
            stray
            and stray[1] == window.process_id()
            and file_dialog_title_matches(stray[2])
        ):
            return
        try:
            dlg = Desktop(backend="uia").window(handle=stray[0])
            cancel = dlg.child_window(title="Cancel", control_type="Button")
            if cancel.exists(timeout=1):
                try:
                    cancel.invoke()
                except Exception:
                    cancel.click_input()
        except Exception:
            pass
        time.sleep(0.4)


# def _find_dialog_controls(dialog):
#     """Return the filename edit and Open/Insert button on a native file dialog."""
#     filename = dialog.child_window(auto_id="3078", control_type="Edit")
#     if not filename.exists(timeout=1):
#         edits = dialog.descendants(control_type="Edit")
#         filename = edits[0] if edits else None

#     open_button = dialog.child_window(auto_id="1", control_type="Button")
#     if not open_button.exists(timeout=1):
#         open_button = None
#         for title in ("Open", "&Open", "Insert", "&Insert"):
#             candidate = dialog.child_window(title=title, control_type="Button")
#             if candidate.exists(timeout=0.5):
#                 open_button = candidate
#                 break

#     if filename is None or open_button is None:
#         return None, None
#     return filename, open_button

def _find_dialog_controls(dialog):
    """Find the filename field and Open/Insert button in a native file dialog."""
    from pywinauto import Desktop

    # Reacquire a WindowSpecification using the dialog's native handle.
    dialog_spec = Desktop(backend="uia").window(handle=dialog.handle)

    filename = dialog_spec.child_window(
        auto_id="3078",
        control_type="Edit",
    )

    if not filename.exists(timeout=1):
        edits = dialog_spec.descendants(control_type="Edit")
        filename = edits[0] if edits else None

    open_button = dialog_spec.child_window(
        auto_id="1",
        control_type="Button",
    )

    if not open_button.exists(timeout=1):
        open_button = None

        for title in ("Open", "&Open", "Insert", "&Insert"):
            candidate = dialog_spec.child_window(
                title=title,
                control_type="Button",
            )

            if candidate.exists(timeout=0.5):
                open_button = candidate
                break

    if filename is None or open_button is None:
        return None, None

    return filename, open_button


def _open_insert_via_menu(window):
    """Fall back to File > Insert when Ctrl+Shift+I does not open the dialog."""
    application_menu = window.child_window(
        title="Application menu",
        control_type="Button",
    )
    if application_menu.exists(timeout=1):
        try:
            application_menu.invoke()
        except Exception:
            application_menu.click_input()
        insert_item = window.child_window(
            title_re=r"Insert.*",
            control_type="MenuItem",
            found_index=0,
        )
        if insert_item.exists(timeout=2):
            try:
                insert_item.invoke()
            except Exception:
                insert_item.click_input()
            return

    from pywinauto.keyboard import send_keys

    send_keys("%f")
    time.sleep(0.3)
    send_keys("n")


def _trigger_insert_dialog(window, timeout=15):
    """Focus JT2Go, send Insert, and wait for the file dialog. Retry while it is busy."""
    deadline = time.monotonic() + timeout
    used_menu = False
    attempt = 0
    while time.monotonic() < deadline:
        _force_window_to_foreground(window)
        try:
            window.set_focus()
        except Exception:
            pass
        time.sleep(0.15)
        try:
            if attempt < 4:
                window.type_keys(INSERT_SHORTCUT)
            elif not used_menu:
                _open_insert_via_menu(window)
                used_menu = True
        except Exception:
            pass
        remaining = max(0.4, min(2.0, deadline - time.monotonic()))
        try:
            return _wait_for_open_dialog(window, timeout=remaining)
        except TimeoutError:
            attempt += 1
            time.sleep(0.3)
    return _wait_for_open_dialog(window, timeout=1)


# def add_file_to_jt2go_window(window, file_path):
#     """Insert a JT file into the current JT2Go session (no new tab)."""
#     if window is None:
#         raise RuntimeError("JT2Go is not open (no JT2Go window found).")

#     _force_window_to_foreground(window)
#     time.sleep(0.05)
#     _close_stray_dialog(window)

#     dialog = _trigger_insert_dialog(window)
#     dialog_handle = dialog.handle
#     _force_window_to_foreground(dialog)
#     time.sleep(0.05)

#     filename, open_button = _find_dialog_controls(dialog)
#     if filename is None or open_button is None:
#         raise RuntimeError("Could not find the filename field or Open button.")

#     _enter_open_dialog_path(filename, open_button, file_path)
#     _wait_for_open_dialog_close(dialog_handle)
#     time.sleep(1.0)

#     try:
#         fresh = find_jt2go_window()
#         if fresh is not None:
#             _force_window_to_foreground(fresh, timeout=3)
#     except Exception as error:
#         print(f"Could not bring JT2Go to the foreground (file inserted): {error}")
