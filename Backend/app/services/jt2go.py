"""Windows UI Automation helpers for opening models in Siemens JT2Go."""

import os
import subprocess
import threading
import time
import uuid
from pathlib import Path


JT2GO_LOCK = threading.Lock()


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
    import ctypes
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


def _wait_for_open_dialog(main_window, timeout=15):
    """Wait for JT2Go's modal Open dialog, including owned popup windows."""
    import ctypes
    from ctypes import wintypes
    from pywinauto import Desktop

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
            and popup[2].strip().lower() == "open"
            and user32.IsWindow(popup[0])
            and user32.IsWindowVisible(popup[0])
        ):
            return desktop.window(handle=popup[0])

        for window in desktop.windows():
            if (
                window.process_id() == main_window.process_id()
                and window.element_info.class_name == "#32770"
                and window.window_text().strip().lower() == "open"
                and window.is_visible()
            ):
                return window
        time.sleep(0.2)
    raise TimeoutError("JT2Go's Open file dialog did not appear.")


def _model_document_windows(main_window):
    return {
        child.handle: child.window_text()
        for child in main_window.descendants(control_type="Window")
        if child.window_text().strip().lower().endswith(".jt")
    }


def _wait_for_new_model_tab(main_window, file_path, existing_handles, timeout=60):
    from comtypes import COMError

    expected_title = Path(file_path).name.casefold()
    deadline = time.monotonic() + timeout
    last_uia_error = None
    while time.monotonic() < deadline:
        try:
            tabs = _model_document_windows(main_window)
            for handle, title in tabs.items():
                if handle not in existing_handles and title.strip().casefold() == expected_title:
                    return
            last_uia_error = None
        except COMError as error:
            last_uia_error = error
        time.sleep(0.2)

    if last_uia_error:
        raise TimeoutError(
            f"JT2Go did not expose the new document tab to UI Automation: {last_uia_error}"
        ) from last_uia_error
    raise TimeoutError(f"JT2Go did not open {Path(file_path).name!r} in a new document tab.")


def add_file_to_jt2go_window(window, file_path):
    """Open a model in a new JT2Go document tab."""
    from pywinauto import Desktop

    if window.is_minimized():
        window.restore()
    window.set_focus()
    existing_tabs = _model_document_windows(window)

    application_menu = window.child_window(
        title="Application menu", control_type="Button"
    )
    if application_menu.exists(timeout=1):
        application_menu.invoke()
        open_item = window.child_window(
            title_re=r"Open\.\.\..*", control_type="MenuItem", found_index=0
        )
        open_item.wait("visible", timeout=5)
        open_item.click_input()
    else:
        window.menu_select("File->Open...")

    dialog = _wait_for_open_dialog(window)
    filename = dialog.child_window(auto_id="3078", control_type="Edit")
    if not filename.exists(timeout=1):
        edits = dialog.descendants(control_type="Edit")
        filename = edits[0] if edits else None
    if filename is None:
        raise RuntimeError("Could not find the filename field in JT2Go's Open dialog.")

    filename.set_edit_text("")
    filename.click_input()
    filename.type_keys(str(file_path), with_spaces=True)
    if os.path.normcase(os.path.normpath(filename.get_value())) != os.path.normcase(
        os.path.normpath(str(file_path))
    ):
        raise RuntimeError("JT2Go's Open dialog did not accept the complete file path.")
    open_button = dialog.child_window(auto_id="1", control_type="Button")
    if not open_button.exists(timeout=1):
        raise RuntimeError("Could not find the Open button in JT2Go's file dialog.")
    open_button.wait("enabled", timeout=5)
    open_button.click_input()
    _wait_for_new_model_tab(window, file_path, set(existing_tabs))
