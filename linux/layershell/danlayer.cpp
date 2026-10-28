// Pin a Qt window above everything, fullscreen games included, on Wayland compositors with
// wlr-layer-shell (niri, KWin, Hyprland, Sway...): the window becomes an overlay-layer surface at
// the same spot, and turns back into a normal window when unpinned. A C API for Python (ctypes),
// over KDE's LayerShellQt. Built against the exact Qt the app bundles (PyQt6's).
#include <LayerShellQt/Window>

#include <QGuiApplication>
#include <QHash>
#include <QMargins>
#include <QScreen>
#include <QWindow>

using LayerShellQt::Window;

static QHash<QWindow *, Window *> s_pinned;

extern "C" {

// 1 when the app runs on Wayland (pinning is possible), else 0
int danlayer_available()
{
    return QGuiApplication::platformName().startsWith(QLatin1String("wayland")) ? 1 : 0;
}

// Make a hidden window an overlay-layer surface with its top-left corner at (x, y) in global
// coordinates; show it afterwards. No keyboard focus unless clicked, so the game keeps its input.
int danlayer_pin(void *qwindow, int x, int y)
{
    auto *win = static_cast<QWindow *>(qwindow);
    if (!win || !danlayer_available() || s_pinned.contains(win))
        return 0;
    QScreen *screen = QGuiApplication::screenAt(QPoint(x + 1, y + 1));
    if (!screen)
        screen = win->screen() ? win->screen() : QGuiApplication::primaryScreen();
    const QRect area = screen->geometry();

    win->destroy();
    Window *layer = Window::get(win);
    layer->setScope(QStringLiteral("overlay"));
    layer->setLayer(Window::LayerOverlay);
    layer->setAnchors(Window::Anchors(Window::AnchorTop | Window::AnchorLeft));
    // margins count from the screen's edge, not from the area bars leave free
    layer->setExclusiveZone(-1);
    layer->setMargins(QMargins(qMax(0, x - area.x()), qMax(0, y - area.y()), 0, 0));
    layer->setKeyboardInteractivity(Window::KeyboardInteractivityOnDemand);
    layer->setActivateOnShow(false);
    layer->setCloseOnDismissed(false);
    layer->setScreen(screen);
    s_pinned.insert(win, layer);
    return 1;
}

// Move a pinned window (global coordinates)
int danlayer_move(void *qwindow, int x, int y)
{
    auto *win = static_cast<QWindow *>(qwindow);
    Window *layer = s_pinned.value(win);
    if (!layer)
        return 0;
    QScreen *screen = win->screen() ? win->screen() : QGuiApplication::primaryScreen();
    const QRect area = screen->geometry();
    layer->setMargins(QMargins(qMax(0, x - area.x()), qMax(0, y - area.y()), 0, 0));
    win->requestUpdate();
    return 1;
}

// Back to a normal window (hide it first, show it afterwards)
int danlayer_unpin(void *qwindow)
{
    auto *win = static_cast<QWindow *>(qwindow);
    Window *layer = s_pinned.take(win);
    if (!layer)
        return 0;
    win->destroy();
    delete layer;
    return 1;
}

int danlayer_is_pinned(void *qwindow)
{
    return s_pinned.contains(static_cast<QWindow *>(qwindow)) ? 1 : 0;
}
}
