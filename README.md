# Daniel for Linux

A Linux port of [Daniel](https://github.com/TheBagelOfMan/Daniel) by TheBagelOfMan: a real-time rice difficulty calculator for 4k osu!mania that runs alongside [tosu](https://tosu.app).

**[Original website](https://thebagelofman.github.io/Daniel/)** · **[Original repository](https://github.com/TheBagelOfMan/Daniel)**

## AppImage

Download `Daniel-x86_64.AppImage` from the [releases](../../releases). Then run:

```bash
chmod +x Daniel-x86_64.AppImage
./Daniel-x86_64.AppImage
```

Python and every library are inside the AppImage. You still need tosu running with osu!, and Wine for the MSD line. osu-winello provides both, see below. A new release is built automatically when a `v*` tag is pushed, and `./build_appimage.sh` builds one locally.

## Install

```bash
git clone https://github.com/apolloKapa/daniel-linux.git
cd daniel-linux
./install.sh
```

Then start **Daniel** from your app menu, or run `daniel`.

The installer only needs `python3`. Everything goes into `~/.local`:

- the app in `~/.local/share/daniel`, with its own Python environment (numpy, pillow, websocket-client)
- the `~/.local/bin/daniel` launcher and a menu entry
- **tosu**: if osu! was installed with [osu-winello](https://github.com/NelloKudo/osu-winello), the installer offers to run `osu-wine --tosu`. After that, tosu starts with osu! automatically. Use `--no-tosu` to skip this.

To update, run `git pull && ./install.sh`. To remove, run `./install.sh --uninstall`. That leaves tosu and osu! untouched.

## How the port works

- **tosu under Wine reports Windows paths** (osu-winello puts osu! on `D:\`, for example). Daniel maps the drive letter through the Wine prefix's `dosdevices` links. It also matches the case of each path component, because Linux filesystems are case-sensitive.
- **MSD skillsets** come from the original `msd.exe` (Etterna's MinaCalc). On Linux it runs through osu-winello's own Wine in osu!'s prefix, or through the system Wine. The results are identical to Windows. Without Wine, the dan estimate still works, but the MSD line shows "MSD Error". Set `DANIEL_WINE` to choose a different Wine, or `MSD_BIN_PATH` to use a native `msd` build.
- **Stays above fullscreen osu!**: on Windows, Daniel is always on top. Wayland compositors (niri, KDE Plasma, Hyprland, Sway, ...) ignore that, and niri hides normal windows behind a fullscreen game. On Linux, Daniel starts **pinned**, as an overlay-layer surface (KDE's LayerShellQt) that stays above everything. Press **P** to unpin or pin it again. To move it, unpin it, drag it, and press P to pin it there. On niri it pins where the window is. On other compositors it pins where it was last pinned. On X11 it just stays on top. The window is drawn with Qt (`src/qt_tk.py` stands in for the few tkinter calls Daniel makes).
- **Fonts**: Segoe UI doesn't exist on Linux, so Daniel uses Noto Sans in bold. Set `DANIEL_FONT` to choose another font, and `DANIEL_FONT_SCALE` to resize the text.

## License

[MIT](LICENSE), © 2026 TheBagelOfMan. Linux port changes are under the same license.
