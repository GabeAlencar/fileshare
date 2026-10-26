# FileShare

Single-file Python app (`fileshare.py`, standard library only) for sending files between devices on a Tailscale network. It wraps Taildrop through the `tailscale` CLI. It has no network listener of its own: the UI server binds `127.0.0.1` on a random port behind a per-launch token.

## Layout

- `fileshare.py`: everything. Tailscale helpers at the top, HTTP handler in the middle, the whole UI (`PAGE`, HTML + CSS + JS) at the bottom.
- `FileShare.bat`, `FileShare.command`, `fileshare.sh`: launchers per OS (the `.sh`/`.command` must stay executable in git).
- `install-linux.sh`: writes `~/.local/share/applications/fileshare.desktop`, which runs with `--quit-when-closed` since there's no terminal.
- `README.md`: user-facing docs. Keep it in sync with behavior changes.

## Behavior to preserve

- **Send**: `tailscale file cp <file> <device>:` (from the browser upload, via a temp dir).
- **Receive**: every 5s the UI POSTs `/api/receive`, which runs `tailscale file get --conflict=rename ~/Downloads/FileShare`.
- **Windows/macOS quirk**: the Tailscale tray app grabs Taildrop files into `~/Downloads` before `file get` can. `adopt_from_parent()` moves files that newly appear in `~/Downloads` (after app start, size stable across two polls, not partial downloads) into `Downloads/FileShare`. It can't tell Taildrop files from browser downloads. Don't make it touch files that existed at startup.
- **Linux**: the default folder follows `XDG_DOWNLOAD_DIR`; `adopt_from_parent()` stays off (no tray app steals files). Error hints target Arch (`pacman`, `systemctl enable --now tailscaled`).
- The UI is deliberately minimal: device list, a drop zone, a received list, one "Open folder" button. Don't re-add manual refresh or check buttons.

## Run and test

- Run: `py fileshare.py` (Windows) or `python3 fileshare.py`. Use `--no-open --port N` to run headless.
- Test without a window: start with `--no-open --port N`, take the token from the printed URL, then call `/api/devices`, `/api/received`, `POST /api/receive` with `?t=<token>`. Use `python -u` if redirecting output, or the URL won't appear.
- The author's setup: the repo lives in WSL (`/home/gabe/fileshare`) but runs with Windows Python via `\\wsl.localhost\Ubuntu\home\gabe\fileshare`. Run git inside WSL (`wsl -e git -C /home/gabe/fileshare ...`). Pushes work through `gh` credentials. The laptop is Arch Linux (no Windows), where it runs natively with `python3`.

## Style

Standard library only, no dependencies. Comments explain why, not what.
