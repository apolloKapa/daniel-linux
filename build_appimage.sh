#!/usr/bin/env bash
# Builds dist/Daniel-x86_64.AppImage: a PyInstaller bundle (Python, Tk, numpy, msd.exe) in an AppDir.
# GitHub Actions runs this on every v* tag (.github/workflows/appimage.yml); locally it needs python3
# with tkinter and appimagetool (APPIMAGETOOL=/path/to/appimagetool, or on PATH).
#   ./build_appimage.sh            full build
#   ./build_appimage.sh --appdir   stop after the AppDir (no appimagetool needed)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

BUILD_DIR="build/appimage"
APPDIR="$BUILD_DIR/Daniel.AppDir"
VENV_DIR="$BUILD_DIR/venv"
VERSION="${DANIEL_VERSION:-$(git describe --tags --always 2>/dev/null || echo dev)}"

python3 -c "import tkinter" || { echo "python3 with tkinter is required"; exit 1; }

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install -q --upgrade pip
# PyQt6's Qt version pinned: linux/layershell builds LayerShellQt against this exact Qt (QT_VERSION)
"$VENV_DIR/bin/python" -m pip install -q pyinstaller numpy pillow websocket-client PyQt6==6.11.0 PyQt6-Qt6==6.11.2

# icon for the window, the menu entry and the AppImage itself
"$VENV_DIR/bin/python" - docs/images/icon.ico "$BUILD_DIR/daniel.png" <<'EOF'
import sys
from PIL import Image
ico = Image.open(sys.argv[1])
ico.size = max(ico.info.get("sizes", [ico.size]))
ico.convert("RGBA").resize((256, 256), Image.LANCZOS).save(sys.argv[2])
EOF

# onedir rather than onefile: nothing to unpack to /tmp on every start. Daniel only draws with
# PIL (Image.new + ImageDraw), so the codec plugins (AVIF/WebP, ~60 MB of libraries) stay out.
"$VENV_DIR/bin/pyinstaller" \
    --noconfirm \
    --clean \
    --onedir \
    --name daniel \
    --distpath "$BUILD_DIR/dist" \
    --workpath "$BUILD_DIR/work" \
    --specpath "$BUILD_DIR" \
    --hidden-import websocket \
    --exclude-module numpy.f2py \
    --exclude-module pytest \
    --exclude-module PIL._avif \
    --exclude-module PIL.AvifImagePlugin \
    --exclude-module PIL._webp \
    --exclude-module PIL.WebPImagePlugin \
    --exclude-module PIL.ImageCms \
    --exclude-module PIL._imagingcms \
    --exclude-module PIL.ImageQt \
    --hidden-import qt_tk \
    --hidden-import linux_pin \
    --exclude-module tkinter \
    --exclude-module PyQt6.QtQml --exclude-module PyQt6.QtQuick --exclude-module PyQt6.QtPdf \
    --exclude-module PyQt6.QtMultimedia --exclude-module PyQt6.QtWebEngineCore --exclude-module PyQt6.QtDesigner \
    --add-data "$ROOT_DIR/src/msd.exe:." \
    src/daniel.py

# Tcl extensions other packages install next to Tcl (graphviz's on Arch) come along with Tk's
# library; drop them, then any bundled library nothing else needs any more
rm -rf "$BUILD_DIR/dist/daniel/_internal/_tcl_data/graphviz"
INTERNAL="$BUILD_DIR/dist/daniel/_internal"
# Qt's UI translations aren't used; its GTK theme plugin would pull in GTK and a second ICU
rm -rf "$INTERNAL/PyQt6/Qt6/translations"
rm -f "$INTERNAL/PyQt6/Qt6/plugins/platformthemes/libqgtk3.so"
# pinning above fullscreen games (linux_pin.py): LayerShellQt + libdanlayer.so, next to the Qt
# they were built for. CI builds them with linux/layershell/build.sh before this script runs.
if [[ -f "$ROOT_DIR/linux/layershell/out/libdanlayer.so" ]]; then
    cp "$ROOT_DIR/linux/layershell/out"/*.so* "$INTERNAL/PyQt6/Qt6/lib/"
else
    echo "WARNING: linux/layershell/out missing: Daniel can't pin above fullscreen games"
fi
# libraries AppImages take from the host (the AppImage excludelist): an older bundled fontconfig
# can't read a newer distro's font config (errors, wrong text size), X11 has to match the server
for lib in libfontconfig.so.1 libfreetype.so.6 libexpat.so.1 libz.so.1 libuuid.so.1 \
           libX11.so.6 libX11-xcb.so.1 libxcb.so.1 libXau.so.6 libXdmcp.so.6 libXext.so.6 \
           libXrender.so.1 libXft.so.2 libXss.so.1 \
           libstdc++.so.6 libgcc_s.so.1 libGL.so.1 libGLX.so.0 libGLdispatch.so.0 libEGL.so.1 \
           libgbm.so.1 libdrm.so.2 libasound.so.2; do
    rm -f "$BUILD_DIR/dist/daniel/_internal/$lib"
done
"$VENV_DIR/bin/python" - "$BUILD_DIR/dist/daniel/_internal" <<'EOF'
import os, subprocess, sys
root = sys.argv[1]
def needed(path):
    out = subprocess.run(["readelf", "-d", path], capture_output=True, text=True).stdout
    return {l.split("[")[1].split("]")[0] for l in out.splitlines() if "(NEEDED)" in l}
def elf(path):
    with open(path, "rb") as f:
        return f.read(4) == b"\x7fELF"
while True:
    files = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs]
    used = set()
    for f in files:
        if not os.path.islink(f) and elf(f):
            used |= needed(f)
    top = [f for f in os.listdir(root) if f.startswith("lib") and ".so" in f]
    unused = [f for f in top if f not in used and not f.startswith("libpython")]
    if not unused:
        break
    for f in unused:
        os.remove(os.path.join(root, f))
    print("pruned:", " ".join(sorted(unused)))
EOF

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -r "$BUILD_DIR/dist/daniel" "$APPDIR/usr/lib/daniel"
# daniel.py looks for icon.png next to itself
cp "$BUILD_DIR/daniel.png" "$APPDIR/usr/lib/daniel/_internal/icon.png"
cp LICENSE "$APPDIR/usr/lib/daniel/LICENSE"

cp "$BUILD_DIR/daniel.png" "$APPDIR/daniel.png"
cp "$BUILD_DIR/daniel.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/daniel.png"
ln -sf daniel.png "$APPDIR/.DirIcon"

cat >"$APPDIR/daniel.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Daniel
GenericName=osu!mania dan calculator
Comment=Real-time 4K rice dan estimate for the map selected in osu! (needs tosu)
Exec=daniel
Icon=daniel
Terminal=false
Categories=Game;Utility;
StartupWMClass=Daniel
X-AppImage-Version=$VERSION
EOF
cp "$APPDIR/daniel.desktop" "$APPDIR/usr/share/applications/daniel.desktop"

cat >"$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/daniel/daniel" "$@"
EOF
chmod +x "$APPDIR/AppRun"

if [[ "${1:-}" == "--appdir" ]]; then
    echo "AppDir ready: $APPDIR"
    exit 0
fi

TOOL="${APPIMAGETOOL:-$(command -v appimagetool || true)}"
[[ -n "$TOOL" ]] || { echo "appimagetool not found (set APPIMAGETOOL)"; exit 1; }
mkdir -p dist
ARCH=x86_64 VERSION="$VERSION" "$TOOL" --no-appstream "$APPDIR" dist/Daniel-x86_64.AppImage
echo "Built dist/Daniel-x86_64.AppImage ($VERSION)"
