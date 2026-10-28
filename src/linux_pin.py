# linux_pin.py -- "pin above everything" for a Qt window on Linux (Wayland).
#
# On Windows a topmost window stays over a fullscreen game. Wayland compositors (niri, KWin,
# Hyprland, Sway...) ignore that request, and niri hides normal windows behind a focused fullscreen
# window. Only layer-shell surfaces on the "overlay" layer stay above it, so pinning turns the window
# into one, at the same spot (libdanlayer.so over KDE's LayerShellQt, see linux/layershell), and
# unpinning turns it back into a normal window.
#
# Where the window goes: niri reports where a floating window is, so it's pinned right there. Other
# compositors (KDE Plasma's KWin, ...) don't tell, so it goes where it was last pinned (remembered in
# ~/.config/<app>/pin.json), top-left at first. A pinned window is moved by dragging it with the left
# mouse button (the compositor can't move layer surfaces, so the app moves itself, see _Dragger).
# On an X11 session the window just gets Qt's stay-on-top flag instead.
#
# Qt window changes have to happen on the GUI thread: call init() on the main thread before the
# event loop starts; toggle()/pin()/unpin() can then be called from any thread.

import ctypes
import json
import logging
import os
import shutil
import subprocess
import sys
import threading

logger = logging.getLogger(__name__)

_lib = None
_lib_failed = False
_relay = None
_dragger = None
_state = {"pinned": False, "pos": None, "widget": None, "x11": False}
_config_path = None


def _load_saved():
    try:
        with open(_config_path, encoding="utf-8") as f:
            data = json.load(f)
        return (int(data["x"]), int(data["y"])), bool(data.get("pinned", False))
    except Exception:
        return None, False


def save_position():
    """Remember where the pinned window is (and whether it's pinned) for the next start."""
    if not _config_path or _state["pos"] is None:
        return
    try:
        os.makedirs(os.path.dirname(_config_path), exist_ok=True)
        with open(_config_path, "w", encoding="utf-8") as f:
            json.dump({"x": _state["pos"][0], "y": _state["pos"][1], "pinned": _state["pinned"]}, f)
    except OSError:
        pass


def was_pinned(default: bool = False) -> bool:
    """Whether the window was pinned when the app last closed (default: never run before)."""
    if not _config_path or not os.path.exists(_config_path):
        return default
    return _load_saved()[1]


def _load_lib():
    """libdanlayer.so sits next to the Qt it was built for (PyQt6/Qt6/lib in the bundle). Loaded
    once Qt runs, so its Qt libraries are already the bundled ones."""
    global _lib, _lib_failed
    if _lib is not None or _lib_failed:
        return _lib
    try:
        import PyQt6
        path = os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", "lib", "libdanlayer.so")
        lib = ctypes.CDLL(path)
        for name in ("danlayer_pin", "danlayer_move"):
            getattr(lib, name).argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        for name in ("danlayer_unpin", "danlayer_is_pinned"):
            getattr(lib, name).argtypes = [ctypes.c_void_p]
        _lib = lib
    except Exception as exc:
        logger.info("linux_pin: layer-shell pinning unavailable (%s)", exc)
        _lib_failed = True
    return _lib


def _is_x11() -> bool:
    try:
        from PyQt6.QtGui import QGuiApplication
        return QGuiApplication.platformName() == "xcb"
    except Exception:
        return False


def available() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    if _is_x11():
        return True
    lib = _load_lib()
    return bool(lib and lib.danlayer_available())


def _host_env():
    try:
        from wine_compat import host_env
        return host_env()
    except Exception:
        return None


def _niri(*args):
    """niri msg -j ...; None when niri isn't running or the call fails."""
    if not os.environ.get("NIRI_SOCKET") or not shutil.which("niri"):
        return None
    try:
        out = subprocess.run(["niri", "msg", "-j", *args], capture_output=True, text=True,
                             timeout=2, env=_host_env())
        return json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else None
    except Exception:
        return None


def _niri_window():
    """This process's window in niri (the newest, if it has several)."""
    windows = _niri("windows") or []
    mine = [w for w in windows if w.get("pid") == os.getpid()]
    return max(mine, key=lambda w: w.get("id", 0)) if mine else None


def _window_global_pos():
    """Where niri has our window (global logical coordinates), or None. niri only reports it for
    floating windows; for a tiled one the window's own screen corner is used instead."""
    win = _niri_window()
    if not win:
        return None
    layout = win.get("layout") or {}
    tile = layout.get("tile_pos_in_workspace_view")
    if not tile:
        return None
    off = layout.get("window_offset_in_tile") or [0, 0]
    workspaces = {w["id"]: w for w in (_niri("workspaces") or [])}
    output_name = (workspaces.get(win.get("workspace_id")) or {}).get("output")
    outputs = _niri("outputs") or {}
    logical = (outputs.get(output_name) or {}).get("logical") or {}
    return (int(logical.get("x", 0) + tile[0] + off[0]), int(logical.get("y", 0) + tile[1] + off[1]))


def _restore_position(pos):
    """After unpinning: float the new normal window and put it back where the overlay was."""
    if not pos:
        return
    win = _niri_window()
    if not win:
        return
    outputs = _niri("outputs") or {}
    workspaces = {w["id"]: w for w in (_niri("workspaces") or [])}
    output_name = (workspaces.get(win.get("workspace_id")) or {}).get("output")
    logical = (outputs.get(output_name) or {}).get("logical") or {}
    env = _host_env()
    wid = str(win["id"])
    if not win.get("is_floating"):
        subprocess.run(["niri", "msg", "action", "move-window-to-floating", "--id", wid],
                       capture_output=True, timeout=2, env=env)
    subprocess.run(["niri", "msg", "action", "move-floating-window", "--id", wid,
                    "-x", str(pos[0] - logical.get("x", 0)), "-y", str(pos[1] - logical.get("y", 0))],
                   capture_output=True, timeout=2, env=env)


def _qwindow_ptr(widget):
    from PyQt6 import sip
    handle = widget.windowHandle()
    return ctypes.c_void_p(sip.unwrapinstance(handle)) if handle is not None else None


def _set_x11_on_top(widget, on):
    from PyQt6.QtCore import Qt
    widget.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
    widget.show()


def _screens():
    from PyQt6.QtGui import QGuiApplication
    return [s.geometry() for s in QGuiApplication.screens()]


def _on_screen(pos, size):
    """pos if the window would be (mostly) visible there, else None."""
    if pos is None:
        return None
    w, h = size
    for g in _screens():
        if g.x() - w // 2 <= pos[0] <= g.x() + g.width() - w // 2 and g.y() <= pos[1] <= g.y() + g.height() - h // 2:
            return pos
    return None


def _default_pos(widget):
    """Top-left of the window's screen (not widget.screen(): pywebview's window shadows it)."""
    from PyQt6.QtGui import QGuiApplication
    handle = widget.windowHandle()
    screen = (handle.screen() if handle is not None else None) or QGuiApplication.primaryScreen()
    geo = screen.geometry() if screen is not None else None
    return (geo.x() + 40, geo.y() + 40) if geo is not None else (40, 40)


def _do_pin(widget, size=None):
    if _state["pinned"]:
        return False
    if _is_x11():
        _set_x11_on_top(widget, True)
        _state.update(pinned=True, widget=widget, x11=True)
        return True
    lib = _load_lib()
    if not lib or not lib.danlayer_available():
        return False
    wsize = size or (widget.width(), widget.height())
    pos = (_on_screen(_window_global_pos(), wsize) or _on_screen(_state["pos"], wsize) or _on_screen(_load_saved()[0], wsize)
           or _default_pos(widget))
    if size:
        widget.resize(*size)
    widget.hide()
    ptr = _qwindow_ptr(widget)
    if ptr is None or not lib.danlayer_pin(ptr, pos[0], pos[1]):
        widget.show()
        return False
    widget.show()
    _state.update(pinned=True, pos=pos, widget=widget)
    save_position()
    global _dragger
    if _dragger is None:
        _dragger = _make_dragger()
    logger.info("linux_pin: pinned at %s", pos)
    return True


def _do_move_by(widget, dx, dy):
    lib = _load_lib()
    if not lib or not _state["pinned"] or _state["x11"] or _state["pos"] is None:
        return False
    x, y = _state["pos"][0] + dx, _state["pos"][1] + dy
    if _on_screen((x, y), (widget.width(), widget.height())) is None:
        return False
    ptr = _qwindow_ptr(widget)
    if ptr is None or not lib.danlayer_move(ptr, x, y):
        return False
    _state["pos"] = (x, y)
    return True


def _do_unpin(widget):
    if not _state["pinned"]:
        return False
    if _state["x11"]:
        _set_x11_on_top(widget, False)
        _state.update(pinned=False, x11=False)
        return True
    lib = _load_lib()
    if not lib:
        return False
    widget.hide()
    ptr = _qwindow_ptr(widget)
    if ptr is None or not lib.danlayer_unpin(ptr):
        widget.show()
        return False
    widget.show()
    _state["pinned"] = False
    save_position()
    pos = _state["pos"]
    threading.Thread(target=_restore_position, args=(pos,), daemon=True).start()
    logger.info("linux_pin: unpinned")
    return True


class _DragState:
    """Left-drag on a pinned window moves it. niri (like other Smithay compositors) keeps a drag's
    pointer coordinates relative to where the surface was when the button went down, so the window
    goes to its start position plus the pointer's offset. Other compositors (KWin, wlroots) give
    coordinates relative to where the surface is now, so they jump when it moves: there it's moved
    by the offset, then motion is ignored until the compositor has had a frame to put it there."""

    THRESHOLD = 5   # px before a press becomes a drag (so clicks still click)
    SETTLE_MS = 20

    def __init__(self):
        self.press = None      # local position of the press
        self.start = None      # where the window was then
        self.dragging = False
        self.settling = False
        self.fixed_origin = bool(os.environ.get("NIRI_SOCKET"))


def _make_dragger():
    from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
    from PyQt6.QtWidgets import QApplication

    class _Dragger(QObject):
        def __init__(self):
            super().__init__()
            self.drag = _DragState()

        def _settled(self):
            self.drag.settling = False

        def eventFilter(self, obj, event):
            widget = _state["widget"]
            if not _state["pinned"] or _state["x11"] or widget is None:
                return False
            try:
                # mouse events reach the top-level QWindow first, in its coordinates
                if obj is not widget.windowHandle():
                    return False
            except RuntimeError:  # the widget is gone (app closing)
                return False
            kind = event.type()
            drag = self.drag
            if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                drag.press = event.position()
                drag.start = _state["pos"]
                drag.dragging = False
            elif kind == QEvent.Type.MouseMove and drag.press is not None:
                if not event.buttons() & Qt.MouseButton.LeftButton:
                    drag.press = None
                    return False
                d = event.position() - drag.press
                if not drag.dragging and abs(d.x()) + abs(d.y()) < drag.THRESHOLD:
                    return False
                drag.dragging = True
                if drag.fixed_origin:
                    x, y = drag.start[0] + int(d.x()), drag.start[1] + int(d.y())
                    _do_move_by(widget, x - _state["pos"][0], y - _state["pos"][1])
                elif not drag.settling and (int(d.x()) or int(d.y())):
                    if _do_move_by(widget, int(d.x()), int(d.y())):
                        drag.settling = True
                        QTimer.singleShot(drag.SETTLE_MS, self._settled)
                return True
            elif kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                if drag.dragging:
                    save_position()
                drag.press = None
                drag.dragging = False
            return False

    dragger = _Dragger()
    QApplication.instance().installEventFilter(dragger)
    return dragger


def init(app_name: str = "danoverlay"):
    """Create the GUI-thread relay. Call on the main thread before the Qt event loop runs."""
    global _relay, _config_path
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    _config_path = os.path.join(config_home, app_name, "pin.json")
    if _relay is not None or not sys.platform.startswith("linux"):
        return
    try:
        from PyQt6.QtCore import QObject, pyqtSignal, Qt
    except Exception:
        return

    class _Relay(QObject):
        request = pyqtSignal(object)

        def __init__(self):
            super().__init__()
            self.request.connect(self._run, Qt.ConnectionType.QueuedConnection)

        def _run(self, job):
            func, args, done = job
            try:
                done["result"] = func(*args)
            except Exception as exc:
                logger.warning("linux_pin: %s failed: %s", func.__name__, exc)
                done["result"] = False
            done["event"].set()

    _relay = _Relay()


def _on_gui_thread(func, *args):
    from PyQt6.QtCore import QThread, QCoreApplication
    app = QCoreApplication.instance()
    if app is not None and QThread.currentThread() == app.thread():
        return func(*args)
    if _relay is None:
        return False
    done = {"event": threading.Event(), "result": False}
    _relay.request.emit((func, args, done))
    done["event"].wait(5)
    return done["result"]


def is_pinned() -> bool:
    return _state["pinned"]


def pin(widget, size=None) -> bool:
    return bool(_on_gui_thread(_do_pin, widget, size))


def unpin(widget) -> bool:
    return bool(_on_gui_thread(_do_unpin, widget))


def move_by(widget, dx: int, dy: int) -> bool:
    """Move a pinned window by (dx, dy) (the compositor can't move layer surfaces). Dragging with
    the mouse already does this."""
    return bool(_on_gui_thread(_do_move_by, widget, dx, dy))


def toggle(widget, size=None) -> bool:
    """Pin or unpin; returns the new pinned state."""
    if _state["pinned"]:
        unpin(widget)
    else:
        pin(widget, size)
    return _state["pinned"]
