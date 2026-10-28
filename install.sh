#!/usr/bin/env bash
# Daniel for Linux: installs into ~/.local (no root needed).
#
#   ./install.sh               install or update
#   ./install.sh --no-tosu     don't offer to set up tosu through osu-winello
#   ./install.sh --uninstall   remove Daniel (leaves tosu and osu! alone)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA_HOME/daniel"
BIN_DIR="$HOME/.local/bin"
DESKTOP_FILE="$DATA_HOME/applications/daniel.desktop"
ICON_FILE="$DATA_HOME/icons/hicolor/256x256/apps/daniel.png"

info() { printf '\033[1;34m::\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

uninstall() {
    rm -rf "$APP_DIR"
    rm -f "$BIN_DIR/daniel" "$DESKTOP_FILE" "$ICON_FILE"
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$DATA_HOME/applications" || true
    info "Daniel removed."
}

SETUP_TOSU=1
for arg in "$@"; do
    case "$arg" in
        --uninstall) uninstall; exit 0 ;;
        --no-tosu) SETUP_TOSU=0 ;;
        -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Unknown option: $arg" ;;
    esac
done

[[ "$(uname -s)" == "Linux" ]] || die "This installer is for Linux."

# --- requirements -----------------------------------------------------------
command -v python3 >/dev/null 2>&1 || die "python3 is required."
python3 -c "import venv, ensurepip" 2>/dev/null || die "Python's venv module is missing (Debian/Ubuntu: sudo apt install python3-venv)."

# --- files ------------------------------------------------------------------
info "Installing to $APP_DIR"
mkdir -p "$APP_DIR" "$BIN_DIR" "$(dirname "$DESKTOP_FILE")" "$(dirname "$ICON_FILE")"
rm -rf "$APP_DIR/src"
cp -r "$REPO_DIR/src" "$APP_DIR/src"
cp "$REPO_DIR/LICENSE" "$APP_DIR/LICENSE"
rm -rf "$APP_DIR/src/__pycache__"

# --- python environment -----------------------------------------------------
if [[ ! -x "$APP_DIR/venv/bin/python" ]]; then
    info "Creating Python environment"
    python3 -m venv "$APP_DIR/venv"
fi
info "Installing Python packages (numpy, pillow, websocket-client, PyQt6)"
"$APP_DIR/venv/bin/python" -m pip install -q --upgrade pip
# the Qt that linux/layershell is built against (pinning above fullscreen games)
"$APP_DIR/venv/bin/python" -m pip install -q numpy pillow websocket-client PyQt6==6.11.0 PyQt6-Qt6==6.11.2
QT_LIB="$("$APP_DIR/venv/bin/python" -c 'import os, PyQt6; print(os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", "lib"))')"
if [[ -f "$REPO_DIR/linux/layershell/out/libdanlayer.so" ]]; then
    cp "$REPO_DIR/linux/layershell/out"/*.so* "$QT_LIB/"
else
    warn "linux/layershell/out missing (built by CI): Daniel can't pin above fullscreen games. The AppImage can."
fi

# --- icon, launcher, menu entry -----------------------------------------------
"$APP_DIR/venv/bin/python" - "$REPO_DIR/docs/images/icon.ico" "$ICON_FILE" "$APP_DIR/src/icon.png" <<'EOF'
import sys
from PIL import Image
ico = Image.open(sys.argv[1])
size = max(ico.info.get("sizes", [ico.size]))
ico.size = size
img = ico.convert("RGBA").resize((256, 256), Image.LANCZOS)
img.save(sys.argv[2])
img.save(sys.argv[3])
EOF

cat >"$BIN_DIR/daniel" <<EOF
#!/usr/bin/env bash
# Daniel (4K osu!mania dan calculator), installed by $REPO_DIR/install.sh
exec "$APP_DIR/venv/bin/python" "$APP_DIR/src/daniel.py" "\$@"
EOF
chmod +x "$BIN_DIR/daniel"

cat >"$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Daniel
GenericName=osu!mania dan calculator
Comment=Real-time 4K rice dan estimate for the map selected in osu! (needs tosu)
Exec=$BIN_DIR/daniel
Icon=daniel
Terminal=false
Categories=Game;Utility;
StartupWMClass=Daniel
EOF
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$DATA_HOME/applications" || true

# --- msd.exe needs Wine --------------------------------------------------------
WINELLO_WINE="$DATA_HOME/osuconfig/wine-osu/bin/wine"
if [[ -x "$WINELLO_WINE" ]]; then
    info "MSD: using osu-winello's Wine ($WINELLO_WINE)"
elif command -v wine >/dev/null 2>&1 || command -v wine64 >/dev/null 2>&1; then
    info "MSD: using the system Wine"
else
    warn "No Wine found: dan levels still work, but the MSD skillset line will show 'MSD Error'.
   Install osu! through osu-winello or install wine to fix it."
fi

# --- tosu (reads the selected map from osu!) -----------------------------------
OSU_WINE="$BIN_DIR/osu-wine"
if [[ -d "$DATA_HOME/osuconfig/tosu" ]]; then
    info "tosu is already set up through osu-winello."
elif [[ $SETUP_TOSU -eq 1 && -x "$OSU_WINE" ]]; then
    answer="y"
    if [[ -t 0 ]]; then
        read -r -p ":: Daniel needs tosu. Set it up with osu-winello now (osu! will start it automatically)? [Y/n] " answer || true
    fi
    if [[ -z "$answer" || "$answer" =~ ^[Yy] ]]; then
        "$OSU_WINE" --tosu || warn "Setting up tosu failed; run 'osu-wine --tosu' yourself later."
    else
        warn "Skipped. Run 'osu-wine --tosu' before using Daniel."
    fi
elif [[ ! -x "$OSU_WINE" ]]; then
    warn "osu-winello not found. Daniel needs tosu (https://github.com/tosuapp/tosu) running next to osu!."
fi

info "Done. Start Daniel from your app menu or run: daniel"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) warn "$BIN_DIR is not on your PATH." ;; esac
