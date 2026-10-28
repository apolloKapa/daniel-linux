# qt_tk.py -- the part of tkinter Daniel uses, on Qt (Linux).
#
# Tk windows can't be pinned above a fullscreen game on Wayland; a Qt window can be turned into an
# overlay-layer surface (linux_pin.py). daniel.py and graph_fast.py use this module as `tk` on Linux,
# so the drawing code stays the same as upstream's.
#
# Covered: Tk (title, geometry, resizable, configure(bg), attributes, after/after_cancel (callable
# from any thread, like Tk), bind("<Tab>"), mainloop, update_idletasks, winfo_rgb, iconphoto,
# iconbitmap, tk.call), Canvas (create_text/rectangle/oval/image, delete, itemconfig(ure), bbox,
# tag_raise, tag_lower, configure, pack) and PhotoImage (width/height + put, data=PPM, file=).

import itertools
import sys
import threading

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget

_app = None


def _ensure_app():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)
    return _app


def _color(value):
    if not value:
        return None
    return QColor(value)


def _font(spec):
    """Tk font tuple: (family, size[, "bold"]); a negative size is in pixels, like Tk."""
    font = QFont()
    if isinstance(spec, (tuple, list)) and spec:
        font.setFamily(str(spec[0]))
        if len(spec) > 1:
            size = int(spec[1])
            if size < 0:
                font.setPixelSize(-size)
            else:
                font.setPointSize(max(1, size))
        styles = " ".join(str(s) for s in spec[2:]).lower()
        font.setBold("bold" in styles)
        font.setItalic("italic" in styles)
    return font


class PhotoImage:
    def __init__(self, master=None, width=0, height=0, file=None, data=None):
        self._image = QImage(max(1, width), max(1, height), QImage.Format.Format_RGB32)
        self._image.fill(QColor("#000000"))
        self._canvases = set()
        if file:
            self._image = QImage(file)
        if data is not None:
            self.configure(data=data)

    def put(self, color, to=None):
        if to is None:
            self._image.fill(QColor(color))
        else:
            x1, y1, x2, y2 = to
            painter = QPainter(self._image)
            painter.fillRect(x1, y1, x2 - x1, y2 - y1, QColor(color))
            painter.end()
        self._changed()

    def configure(self, data=None, **_):
        if data is not None:
            image = QImage.fromData(bytes(data))
            if not image.isNull():
                self._image = image
                self._changed()

    config = configure

    def width(self):
        return self._image.width()

    def height(self):
        return self._image.height()

    def _changed(self):
        for canvas in self._canvases:
            canvas.update()


class _Item:
    __slots__ = ("kind", "coords", "opts")

    def __init__(self, kind, coords, opts):
        self.kind, self.coords, self.opts = kind, list(coords), opts


class Canvas(QWidget):
    def __init__(self, master, width=0, height=0, bg="#000000", highlightthickness=0, **_):
        super().__init__(master)
        self._ids = itertools.count(1)
        self._items = {}
        self._order = []
        self._bg = _color(bg) or QColor("#000000")
        self.resize(width, height)
        if isinstance(master, Tk):
            master._canvas = self

    # -- items --------------------------------------------------------------
    def _add(self, kind, coords, opts):
        item_id = next(self._ids)
        self._items[item_id] = _Item(kind, coords, opts)
        self._order.append(item_id)
        if kind == "image" and opts.get("image") is not None:
            opts["image"]._canvases.add(self)
        self.update()
        return item_id

    def create_text(self, x, y, **opts):
        return self._add("text", (x, y), opts)

    def create_rectangle(self, x1, y1, x2, y2, **opts):
        return self._add("rect", (x1, y1, x2, y2), opts)

    def create_oval(self, x1, y1, x2, y2, **opts):
        return self._add("oval", (x1, y1, x2, y2), opts)

    def create_image(self, x, y, **opts):
        return self._add("image", (x, y), opts)

    def delete(self, *items):
        for item in items:
            if item == "all":
                self._items.clear()
                self._order.clear()
                break
            if item in self._items:
                del self._items[item]
                self._order.remove(item)
        self.update()

    def itemconfigure(self, item, **opts):
        if item in self._items:
            self._items[item].opts.update(opts)
            self.update()

    itemconfig = itemconfigure

    def tag_raise(self, item, above=None):
        if item not in self._items:
            return
        self._order.remove(item)
        if above in self._items:
            self._order.insert(self._order.index(above) + 1, item)
        else:
            self._order.append(item)
        self.update()

    def tag_lower(self, item, below=None):
        if item not in self._items:
            return
        self._order.remove(item)
        if below in self._items:
            self._order.insert(self._order.index(below), item)
        else:
            self._order.insert(0, item)
        self.update()

    def bbox(self, item):
        it = self._items.get(item)
        if it is None:
            return None
        rect = self._item_rect(it)
        return (int(rect.left()), int(rect.top()), int(rect.right()), int(rect.bottom()))

    def configure(self, width=None, height=None, bg=None, **_):
        if bg is not None:
            self._bg = _color(bg) or self._bg
        if width is not None or height is not None:
            self.resize(width or self.width(), height or self.height())
        self.update()

    config = configure

    def pack(self, **_):
        parent = self.parentWidget()
        if parent is not None:
            self.resize(parent.size())

    # -- geometry and painting ---------------------------------------------------
    @staticmethod
    def _anchored(x, y, w, h, anchor):
        anchor = anchor or "center"
        if "w" in anchor:
            left = x
        elif "e" in anchor:
            left = x - w
        else:
            left = x - w / 2
        if "n" in anchor:
            top = y
        elif "s" in anchor:
            top = y - h
        else:
            top = y - h / 2
        return QRectF(left, top, w, h)

    def _item_rect(self, it):
        if it.kind == "text":
            metrics = QFontMetricsF(_font(it.opts.get("font")))
            text = str(it.opts.get("text", ""))
            return self._anchored(it.coords[0], it.coords[1], metrics.horizontalAdvance(text), metrics.height(), it.opts.get("anchor"))
        if it.kind == "image":
            img = it.opts.get("image")
            w, h = (img.width(), img.height()) if img else (0, 0)
            return self._anchored(it.coords[0], it.coords[1], w, h, it.opts.get("anchor"))
        x1, y1, x2, y2 = it.coords
        return QRectF(QPointF(x1, y1), QPointF(x2, y2)).normalized()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.fillRect(self.rect(), self._bg)
        for item_id in list(self._order):
            it = self._items.get(item_id)
            if it is None or it.opts.get("state") == "hidden":
                continue
            if it.kind == "text":
                color = _color(it.opts.get("fill")) or QColor("#000000")
                font = _font(it.opts.get("font"))
                painter.setFont(font)
                painter.setPen(color)
                rect = self._item_rect(it)
                ascent = QFontMetricsF(font).ascent()
                painter.drawText(QPointF(rect.left(), rect.top() + ascent), str(it.opts.get("text", "")))
            elif it.kind == "image":
                img = it.opts.get("image")
                if img is not None:
                    painter.drawImage(self._item_rect(it).topLeft(), img._image)
            else:
                fill = _color(it.opts.get("fill"))
                outline = _color(it.opts.get("outline"))
                painter.setPen(outline if outline else Qt.PenStyle.NoPen)
                painter.setBrush(fill if fill else Qt.BrushStyle.NoBrush)
                x1, y1, x2, y2 = it.coords
                rect = QRectF(QPointF(x1, y1), QPointF(x2, y2)).normalized()
                if it.kind == "oval":
                    painter.drawEllipse(rect)
                elif fill is not None and outline is None:
                    # Tk rectangles include their bottom/right edge pixel
                    painter.fillRect(rect.adjusted(0, 0, 1, 1), fill)
                else:
                    painter.drawRect(rect)
        painter.end()


class _Relay(QObject):
    call = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(self._run, Qt.ConnectionType.QueuedConnection)

    @staticmethod
    def _run(func):
        func()


class Tk(QWidget):
    """The main window. Pin key and dragging: see linux_pin (pinned windows can't be moved by the
    compositor, so dragging the window with the left button moves it while pinned)."""

    def __init__(self, className="daniel"):
        app = _ensure_app()
        app.setApplicationName(className)
        app.setDesktopFileName(className)
        super().__init__()
        self._canvas = None
        self._bindings = {}
        self._timers = {}
        self._timer_ids = itertools.count(1)
        self._relay = _Relay()
        self._main_thread = threading.main_thread()
        self._drag_from = None
        self.tk = self  # root.tk.call(...)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # -- tkinter API ---------------------------------------------------------------
    def call(self, *args):
        return None

    def title(self, text):
        self.setWindowTitle(text)

    def geometry(self, spec):
        size = spec.split("+")[0]
        w, h = (int(v) for v in size.split("x"))
        self.setFixedSize(w, h)
        if self._canvas is not None:
            self._canvas.resize(w, h)

    def resizable(self, *_):
        pass

    def configure(self, bg=None, **_):
        if bg:
            self.setStyleSheet(f"background:{bg};")

    config = configure

    def attributes(self, *args):
        pass

    def update_idletasks(self):
        QApplication.processEvents()

    def winfo_rgb(self, color):
        c = QColor(color)
        return c.red() * 257, c.green() * 257, c.blue() * 257

    def iconbitmap(self, *_):
        pass

    def iconphoto(self, _default, image):
        self.setWindowIcon(QIcon(QPixmap.fromImage(image._image)))

    def bind(self, sequence, func):
        self._bindings[sequence] = func

    def after(self, ms, func):
        """Run func on the GUI thread after ms milliseconds; callable from any thread, like Tk."""
        timer_id = next(self._timer_ids)

        def schedule():
            timer = QTimer(self)
            timer.setSingleShot(True)

            def fire():
                self._timers.pop(timer_id, None)
                timer.deleteLater()
                func()

            timer.timeout.connect(fire)
            self._timers[timer_id] = timer
            timer.start(int(ms))

        if threading.current_thread() is self._main_thread:
            schedule()
        else:
            self._relay.call.emit(schedule)
        return timer_id

    def after_cancel(self, timer_id):
        timer = self._timers.pop(timer_id, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def mainloop(self):
        self.show()
        _app.exec()

    # -- Qt events ------------------------------------------------------------------
    def keyPressEvent(self, event):
        names = {Qt.Key.Key_Tab: "<Tab>"}
        func = self._bindings.get(names.get(event.key()))
        if func is None and event.text():
            func = self._bindings.get(f"<Key-{event.text()}>") or self._bindings.get(event.text())
        if func is not None:
            func(None)
        else:
            super().keyPressEvent(event)

    def event(self, event):
        # Tab normally moves focus between widgets; here it's a key binding
        if event.type() == event.Type.KeyPress and event.key() == Qt.Key.Key_Tab:
            self.keyPressEvent(event)
            return True
        return super().event(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            import linux_pin
            if linux_pin.is_pinned():
                # a layer surface has no position Qt knows: move it so the point grabbed stays
                # under the pointer
                self._drag_from = event.position()
            elif self.windowHandle() is not None:
                # unpinned: let the compositor move the window
                self.windowHandle().startSystemMove()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_from is not None:
            import linux_pin
            delta = event.position() - self._drag_from
            linux_pin.move_by(self, int(delta.x()), int(delta.y()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_from is not None:
            import linux_pin
            linux_pin.save_position()
        self._drag_from = None
        super().mouseReleaseEvent(event)
