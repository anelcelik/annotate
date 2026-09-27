"""
platform_win.py — the parts of Windows that depend on how the app was installed.

The Store build runs as an MSIX package, and a package plays by different
rules than a loose .exe:

  • Start on boot. A package's writes to HKCU are redirected into a private
    copy of the registry that nothing reads at sign-in, so the Run key does
    nothing (and reading it back even claims it worked). Packages declare a
    StartupTask in AppxManifest.xml and switch it with
    Windows.ApplicationModel.StartupTask instead. A task also can't pass
    command-line arguments, so "was I started at sign-in?" is answered by the
    activation kind rather than by --minimized.

  • Store rating. A packaged app can open the Store's own rating dialog on
    top of itself (StoreContext.RequestRateAndReviewAppAsync) instead of
    throwing the user out to the Store app.

Everything here degrades quietly: from source, from the portable .exe or off
Windows, the packaged paths report "not available" and the callers fall back.
The WinRT calls go through pywinrt (winrt-* packages), imported lazily so a
build without them still starts.
"""

import os
import platform
import sys
import threading

IS_WIN = platform.system() == "Windows"

STARTUP_TASK_ID = "ScreenAnnotatorProStartup"   # must match AppxManifest.xml
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "ScreenAnnotatorPro"
APPMODEL_ERROR_NO_PACKAGE = 15700

_packaged: bool | None = None


def is_packaged() -> bool:
    """True when running with package identity (Store / MSIX install)."""
    global _packaged
    if _packaged is not None:
        return _packaged
    _packaged = False
    if IS_WIN:
        try:
            import ctypes
            from ctypes import wintypes
            length = wintypes.UINT(0)
            rc = ctypes.windll.kernel32.GetCurrentPackageFullName(
                ctypes.byref(length), None)
            _packaged = rc != APPMODEL_ERROR_NO_PACKAGE
        except Exception:
            _packaged = False
    return _packaged


def _wait(operation_factory, timeout: float = 8.0):
    """Run one WinRT async operation to completion on a worker thread.

    Blocking on an async operation is not allowed on the GUI thread (it is a
    single-threaded apartment); a plain worker thread joins the multithreaded
    apartment implicitly, where waiting is fine.
    """
    box = {}

    def work():
        try:
            box["value"] = operation_factory().get()
        except Exception as e:           # surfaced to the caller below
            box["error"] = e

    t = threading.Thread(target=work, daemon=True, name="winrt-wait")
    t.start()
    t.join(timeout)
    if "error" in box:
        raise box["error"]
    if "value" not in box:
        raise TimeoutError("Windows did not answer in time")
    return box["value"]


# ── Start on boot ────────────────────────────────────────────────────────────

def _startup_exe() -> str:
    return sys.executable if getattr(sys, "frozen", False) \
        else os.path.abspath(sys.argv[0])


def _registry_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
        return True
    except OSError:
        return False


def _registry_set(enable: bool) -> tuple[bool, str]:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_READ) as key:
            if enable:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ,
                                  f'"{_startup_exe()}" --minimized')
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                except FileNotFoundError:
                    pass
        return True, ""
    except OSError as e:
        return False, f"Windows refused the change: {e}"


def startup_status() -> str:
    """"on", "off", "blocked" (turned off in Windows Settings or by policy —
    only the user can undo that) or "unsupported"."""
    if not IS_WIN:
        return "unsupported"
    if not is_packaged():
        return "on" if _registry_enabled() else "off"
    try:
        from winrt.windows.applicationmodel import StartupTask, StartupTaskState
        task = _wait(lambda: StartupTask.get_async(STARTUP_TASK_ID))
        state = task.state
        if state in (StartupTaskState.ENABLED, StartupTaskState.ENABLED_BY_POLICY):
            return "on"
        if state in (StartupTaskState.DISABLED_BY_USER,
                     StartupTaskState.DISABLED_BY_POLICY):
            return "blocked"
        return "off"
    except Exception:
        return "unsupported"


BLOCKED_MESSAGE = (
    "Windows has start-up turned off for Screen Annotator Pro, and only you "
    "can turn it back on: Settings → Apps → Startup, then switch on Screen "
    "Annotator Pro.")


def set_startup(enable: bool) -> tuple[bool, str]:
    """Switch start-on-boot. Returns (ok, message-for-the-user)."""
    if not IS_WIN:
        return False, "Start on boot is only available on Windows."
    if not is_packaged():
        return _registry_set(enable)
    try:
        from winrt.windows.applicationmodel import StartupTask, StartupTaskState
        task = _wait(lambda: StartupTask.get_async(STARTUP_TASK_ID))
        if not enable:
            task.disable()
            return True, ""
        state = task.state
        if state not in (StartupTaskState.ENABLED, StartupTaskState.ENABLED_BY_POLICY):
            state = _wait(task.request_enable_async)
        if state in (StartupTaskState.ENABLED, StartupTaskState.ENABLED_BY_POLICY):
            return True, ""
        return False, BLOCKED_MESSAGE
    except Exception as e:
        return False, f"Windows didn't accept the change ({type(e).__name__})."


def launched_at_startup() -> bool:
    """Was this launch the sign-in start (so the app should stay in the tray)?"""
    if "--minimized" in sys.argv:
        return True
    if not is_packaged():
        return False
    try:
        from winrt.windows.applicationmodel import AppInstance
        from winrt.windows.applicationmodel.activation import ActivationKind
        args = AppInstance.get_activated_event_args()
        return args is not None and args.kind == ActivationKind.STARTUP_TASK
    except Exception:
        return False


# ── Store rating dialog ──────────────────────────────────────────────────────

_pending = []      # keeps in-flight WinRT objects alive until they finish


def request_store_rating(hwnd: int, on_done) -> bool:
    """Open the Store's rating dialog over our window.

    Returns False when that is not possible (not packaged, pywinrt missing),
    so the caller can fall back to the ms-windows-store:// link. `on_done`
    gets True if the user submitted a rating, False otherwise — called from a
    worker thread, so marshal back to the GUI thread before touching widgets.
    """
    if not is_packaged():
        return False
    try:
        from winrt.runtime.interop import initialize_with_window
        from winrt.windows.services.store import (
            StoreContext, StoreRateAndReviewStatus)
        context = StoreContext.get_default()
        initialize_with_window(context, int(hwnd))
        operation = context.request_rate_and_review_app_async()
    except Exception:
        return False

    entry = (context, operation)
    _pending.append(entry)

    def finished(op, _status):
        rated = False
        try:
            rated = op.get_results().status == StoreRateAndReviewStatus.SUCCEEDED
        except Exception:
            pass
        finally:
            try:
                _pending.remove(entry)
            except ValueError:
                pass
        on_done(rated)

    operation.completed = finished
    return True
