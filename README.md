# FileShare

A small app for sending files between the devices on your Tailscale network. Pick a device, drop files, done. The same window checks for files other devices send you.

It is built on Taildrop (Tailscale's own file sending), so there's nothing to set up on the other side: any device running Tailscale can receive, including phones.

![screenshot](screenshot.png)

## Run it

You need Python 3.8+ and Tailscale installed and logged in. No other installs.

| OS | Start it by |
|---|---|
| Windows | double-click `FileShare.bat` (or `py fileshare.py`) |
| macOS | double-click `FileShare.command` (or `python3 fileshare.py`) |
| Linux | `./fileshare.sh` (or `python3 fileshare.py`), or run `./install-linux.sh` once to add it to your app launcher |

It opens in its own window when Chrome, Edge or Chromium is installed, otherwise in a browser tab. On macOS/Linux, stop it with Ctrl+C in the terminal; on Windows, end `pythonw` or use the terminal version.

**Linux only, once:** receiving needs permission to talk to Tailscale without sudo:

    sudo tailscale set --operator=$USER

### Arch Linux setup

Arch installs Tailscale but doesn't start it, so a fresh machine needs:

    sudo pacman -S --needed python tailscale xdg-utils
    sudo systemctl enable --now tailscaled
    sudo tailscale up
    sudo tailscale set --operator=$USER
    ./install-linux.sh                     # optional: adds FileShare to the app launcher

For the chromeless window, install `chromium` (or Chrome, Edge, Brave or Vivaldi from the AUR); otherwise it opens in your default browser. When started from the launcher there's no terminal to Ctrl+C, so it quits on its own about three minutes after you close the window (`--quit-when-closed`). Remove the launcher entry with `./install-linux.sh --uninstall`.

## How it works

- **Devices** come from `tailscale status --json`. Green dot means online. Taildrop only sends to devices logged in as you.
- **Send**: drop files (or click the box) and each one goes out with `tailscale file cp`.
- **Received**: every 5 seconds it runs `tailscale file get` and saves anything waiting to `~/Downloads/FileShare` (on Linux, the `FileShare` folder inside your XDG download dir). Same-name files get renamed, not overwritten. Change the folder with `--downloads PATH`.

The window talks to a tiny server on `127.0.0.1` only, protected by a random per-launch token, so nothing outside your computer can use it.

## Notes

- On macOS and Windows the official Tailscale app may catch incoming files itself and put them in your Downloads folder. So while FileShare is open, any file that newly appears in Downloads is moved into `Downloads/FileShare` (it can't tell a Taildrop file from a browser download, so both are moved).
- On Linux nothing grabs Taildrop files behind FileShare's back, so your Downloads folder is left alone.
- Options: `--downloads DIR`, `--port N`, `--no-open`, `--quit-when-closed`.
