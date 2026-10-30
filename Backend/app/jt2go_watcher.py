import socket
import subprocess
import sys
import time

from app.services import jt2go

_instance_lock = None

APP_TITLE = "JT Viewer"
INSERT_TITLES = {"insert file", "insert", "open", "open file"}
CLOSE_JT2GO_DIALOG = True  # close JT2Go's "Insert File" dialog when the app opens


def find_app_window():
    from pywinauto import Desktop
    for w in Desktop(backend="uia").windows():
        try:
            if w.window_text().strip() == APP_TITLE:
                return w
        except Exception:
            continue
    return None


def force_foreground(hwnd):
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.SetWindowPos.argtypes = (
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    )
    user32.BringWindowToTop.argtypes = (wintypes.HWND,)
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)

    hwnd = wintypes.HWND(hwnd)
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE

    foreground = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    my_tid = kernel32.GetCurrentThreadId()
    attached = bool(fg_tid and fg_tid != my_tid and user32.AttachThreadInput(my_tid, fg_tid, True))
    try:
        flags = 0x0001 | 0x0002  # SWP_NOSIZE | SWP_NOMOVE
        user32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, flags)  # topmost
        user32.SetWindowPos(hwnd, wintypes.HWND(-2), 0, 0, 0, 0, flags)  # back to normal
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(my_tid, fg_tid, False)


def launch_or_focus():
    win = find_app_window()
    if win is None:
        print("Launching JT Viewer...")
        log = open(r"C:\Project\new\Backend\desktop_app.log", "ab")
        subprocess.Popen(
            [r"C:\Project\new\venv\Scripts\python.exe", r"C:\Project\new\Backend\Desktop_app.py"],
            cwd=r"C:\Project\new\Backend",
            stdout=log,
            stderr=log,
        )
        deadline = time.monotonic() + 20
        while win is None and time.monotonic() < deadline:
            time.sleep(0.3)
            win = find_app_window()
    if win is not None:
        try:
            force_foreground(win.handle)
        except Exception as error:
            print("Could not bring the app to the front:", error)

def _popup_gone(handle):
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindow.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    h = wintypes.HWND(handle)
    for _ in range(10):  # wait up to ~1s
        if not user32.IsWindow(h) or not user32.IsWindowVisible(h):
            return True
        time.sleep(0.1)
    return False


def close_popup(handle):
    import ctypes
    from ctypes import wintypes
    from pywinauto import Desktop

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    hwnd = wintypes.HWND(handle)

    # 1. Click the "Cancel" button found by its text (UI Automation)
    try:
        dlg = Desktop(backend="uia").window(handle=handle)
        btn = dlg.child_window(title="Cancel", control_type="Button")
        if btn.exists(timeout=1):
            try:
                btn.invoke()
            except Exception:
                btn.click_input()
            if _popup_gone(handle):
                print("Insert File dialog closed (Cancel button).")
                return
    except Exception as error:
        print("Cancel button method failed:", error)

    # 2. System close command (same as clicking the X)
    user32.PostMessageW(hwnd, 0x0112, 0xF060, 0)  # WM_SYSCOMMAND, SC_CLOSE
    if _popup_gone(handle):
        print("Insert File dialog closed (SC_CLOSE).")
        return

    # 3. WM_CLOSE
    user32.PostMessageW(hwnd, 0x0010, 0, 0)
    if _popup_gone(handle):
        print("Insert File dialog closed (WM_CLOSE).")
        return

    # 4. Last resort: focus the dialog and press Esc
    try:
        Desktop(backend="uia").window(handle=handle).set_focus()
        Desktop(backend="uia").window(handle=handle).type_keys("{ESC}")
        if _popup_gone(handle):
            print("Insert File dialog closed (Esc).")
            return
    except Exception as error:
        print("Esc method failed:", error)

    print("Could not close the Insert File dialog.")

# def watch(interval=0.5):
#     print("Watching JT2Go... (Ctrl+C to stop)")
#     last_handle = None
#     while True:
#         try:
#             window = jt2go.find_jt2go_window()
#             popup = jt2go._active_popup(window) if window else None
#             handle = popup[0] if popup else None
#             if popup and handle != last_handle:
#                 title = popup[2].strip().lower()
#                 if title and title != "project workspace":
#                     print(f"JT2Go dialog appearedww: {popup[2]!r}")
#                 if not jt2go.JT2GO_LOCK.locked() and title in INSERT_TITLES:
#                     if CLOSE_JT2GO_DIALOG:
#                         close_popup(handle)   # close first, so it can't cover your app
#                         time.sleep(0.3)
#                     launch_or_focus()
#             last_handle = handle
#         except Exception as error:
#             print("watcher:", error)
#         time.sleep(interval)
def automation_in_progress():
    """True while JT Studio is driving JT2Go so the watcher must not close its dialog."""
    return jt2go.BUSY_FLAG.exists()


def should_intercept_insert(title):
    """User Insert in JT2Go should open JT Viewer; our own automation must be ignored."""
    normalized = (title or "").strip().lower()
    if normalized not in INSERT_TITLES:
        return False
    return not automation_in_progress()


def watch(interval=0.5):
    print("Watching JT2Go... (Ctrl+C to stop)")
    last_handle = None
    while True:
        try:
            window = jt2go.find_jt2go_window()
            popup = jt2go._active_popup(window) if window else None
            handle = popup[0] if popup else None
            if popup and handle != last_handle:
                title = popup[2].strip().lower()
                if title and title != "project workspace":
                    print(f"JT2Go dialog appearedxxxx: {popup[2]!r}")
                if should_intercept_insert(title):
                    print("Insert detected, opening JT Viewer...")
                    last_handle = handle  # don't re-trigger while we work
                    try:
                        launch_or_focus()
                    except Exception as error:
                        print("launch failed:", error)
                    if CLOSE_JT2GO_DIALOG:
                        try:
                            close_popup(handle)
                        except Exception as error:
                            print("close failed:", error)
                    try:
                        w = find_app_window()
                        if w is not None:
                            force_foreground(w.handle)  # bring to front again after the dialog closes
                    except Exception as error:
                        print("focus failed:", error)
                    continue
            last_handle = handle
        except Exception as error:
            print("watcher:", error)
        time.sleep(interval)

def claim_single_instance():
    """Bind a local port so a second watcher process exits immediately."""
    global _instance_lock
    _instance_lock = socket.socket()
    try:
        _instance_lock.bind(("127.0.0.1", 50998))
    except OSError:
        print("Watcher already running.")
        sys.exit(0)


if __name__ == "__main__":
    claim_single_instance()
    watch()