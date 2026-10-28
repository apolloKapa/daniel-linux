import json
import os
import shutil
import subprocess
import sys

BASE_DIR = os.path.dirname(__file__)


def _osu_winello_dirs():
    data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(data, "osuconfig"), os.path.join(data, "wineprefixes", "osu-wineprefix")


def find_wine():
    """Wine to run msd.exe with: DANIEL_WINE, osu-winello's own Wine, then the system's."""
    env_wine = os.environ.get("DANIEL_WINE")
    if env_wine:
        return env_wine
    osuconfig, _ = _osu_winello_dirs()
    winello_wine = os.path.join(osuconfig, "wine-osu", "bin", "wine")
    if os.access(winello_wine, os.X_OK):
        return winello_wine
    return shutil.which("wine64") or shutil.which("wine")


def wine_prefix():
    """The Wine prefix osu! runs in (osu-winello's), so msd.exe finds the VC++ runtime there."""
    if os.environ.get("WINEPREFIX"):
        return os.environ["WINEPREFIX"]
    _, prefix = _osu_winello_dirs()
    return prefix if os.path.isdir(prefix) else None


def _resolve_msd_command():
    env_path = os.environ.get("MSD_BIN_PATH")
    if env_path:
        if os.name != "nt" and env_path.lower().endswith(".exe"):
            wine = find_wine()
            if wine:
                return [wine, env_path], env_path
        return [env_path], env_path

    windows_msd = os.path.join(BASE_DIR, "msd.exe")
    native_msd = os.path.join(BASE_DIR, "msd")

    if os.name == "nt":
        return [windows_msd], windows_msd

    if os.path.exists(native_msd):
        return [native_msd], native_msd

    if os.path.exists(windows_msd):
        wine = find_wine()
        if wine:
            return [wine, windows_msd], windows_msd

    return [native_msd], native_msd


def parse_hitobjects(osu_file, mod="NM"):
    hitobjects = []
    in_section = False

    with open(osu_file, "r", encoding="utf8") as f:
        for line in f:
            line = line.strip()

            if line == "[HitObjects]":
                in_section = True
                continue

            if not in_section or not line:
                continue

            parts = line.split(",")
            x = int(parts[0])
            time = int(parts[2])
            obj_type = int(parts[3])

            if mod == "DT":
                time = int(time * 2 / 3)
            elif mod == "HT":
                time = int(time * 4 / 3)

            hitobjects.append({"x": x, "time": time, "type": obj_type})

    return hitobjects


def osu_to_etterna_rows(hitobjects, keycount=4):
    rows = {}
    column_width = 512 / keycount

    for obj in hitobjects:
        time = round(obj["time"] / 1000.0, 4)
        column = int(obj["x"] // column_width)
        rows[time] = rows.get(time, 0) | (1 << column)
        # LN releases are intentionally ignored (obj_type & 128)

    return [{"notes": rows[t], "time": t} for t in sorted(rows)]


def calculate_msd(notes):
    cmd, msd_path = _resolve_msd_command()

    if not os.path.exists(msd_path):
        raise FileNotFoundError(
            f"MSD binary not found at '{msd_path}'. Set MSD_BIN_PATH or add a compatible executable to src/."
        )

    if os.name != "nt" and msd_path.lower().endswith(".exe") and len(cmd) == 1:
        raise RuntimeError(
            "Found msd.exe on Linux/macOS, but Wine is not installed. Install Wine or provide a native msd via MSD_BIN_PATH."
        )

    popen_kwargs = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    }

    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    elif len(cmd) > 1:
        # msd.exe through Wine: osu!'s prefix, and none of Wine's own chatter on stderr
        env = dict(os.environ, WINEDEBUG="-all")
        prefix = wine_prefix()
        if prefix:
            env["WINEPREFIX"] = prefix
        popen_kwargs["env"] = env

    p = subprocess.Popen(cmd, **popen_kwargs)
    output, err = p.communicate(json.dumps(notes))

    # Wine prints status lines ("fsync: up and running") even when msd.exe works
    if err and (p.returncode != 0 or not output.strip()):
        print("MSD ERROR:", err, file=sys.stderr)

    return json.loads(output)
