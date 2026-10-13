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
| Linux | `./fileshare.sh` (or `python3 fileshare.py`) |

It opens in its own window when Chrome, Edge or Chromium is installed, otherwise in a browser tab. On macOS/Linux, stop it with Ctrl+C in the terminal; on Windows, end `pythonw` or use the terminal version.

**Linux only, once:** receiving needs permission to talk to Tailscale without sudo:

    sudo tailscale set --operator=$USER

## How it works

- **Devices** come from `tailscale status --json`. Green dot means online. Taildrop only sends to devices logged in as you.
- **Send**: drop files (or click the box) and each one goes out with `tailscale file cp`.
- **Received**: every 5 seconds (or when you press *Check now*) it runs `tailscale file get` and saves anything waiting to `~/Downloads/FileShare`. Same-name files get renamed, not overwritten. Change the folder with `--downloads PATH`.

The window talks to a tiny server on `127.0.0.1` only, protected by a random per-launch token, so nothing outside your computer can use it.

## Notes

- On macOS and Windows the official Tailscale app may catch incoming files itself and put them in your Downloads folder, in which case they land there instead of in this app's list.
- Options: `--downloads DIR`, `--port N`, `--no-open`.
