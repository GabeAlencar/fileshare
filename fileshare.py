#!/usr/bin/env python3
"""FileShare: drag-and-drop file sending between devices on your Tailscale network.

Built on Taildrop through the local `tailscale` CLI. Pure Python standard library,
no installs needed. Run it and a window opens:

    python3 fileshare.py            (Windows: py fileshare.py)

Options:
    --downloads DIR   where received files are saved (default: ~/Downloads/FileShare)
    --port N          local port for the UI (default: random free port)
    --no-open         don't open a window, just print the URL
"""

import argparse
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = secrets.token_urlsafe(16)
DOWNLOADS = None
TAILSCALE = None
RECEIVE_LOCK = threading.Lock()


# ---------------------------------------------------------------- tailscale ---

def find_tailscale():
    found = shutil.which("tailscale")
    if found:
        return found
    candidates = []
    system = platform.system()
    if system == "Darwin":
        candidates = [
            "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
            "/usr/local/bin/tailscale",
            "/opt/homebrew/bin/tailscale",
        ]
    elif system == "Windows":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if base:
                candidates.append(os.path.join(base, "Tailscale", "tailscale.exe"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def run_tailscale(*args, timeout=600):
    if not TAILSCALE:
        raise RuntimeError("Couldn't find the tailscale command. Is Tailscale installed?")
    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [TAILSCALE, *args], capture_output=True, text=True, timeout=timeout, **kwargs
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip() or f"tailscale exited with {proc.returncode}"
        raise RuntimeError(explain_error(msg))
    return proc.stdout


def explain_error(msg):
    low = msg.lower()
    if "access denied" in low or "permission denied" in low or "operator" in low:
        if platform.system() == "Linux":
            return msg + "\n\nFix once with:  sudo tailscale set --operator=$USER"
    if "not running" in low or "failed to connect" in low:
        return msg + "\n\nIs Tailscale running and logged in?"
    return msg


def short_name(peer):
    dns = (peer.get("DNSName") or "").rstrip(".")
    return dns.split(".")[0] if dns else peer.get("HostName", "?")


def list_devices():
    status = json.loads(run_tailscale("status", "--json", timeout=20))
    self_peer = status.get("Self") or {}
    me = short_name(self_peer) if self_peer else ""
    devices = []
    for peer in (status.get("Peer") or {}).values():
        ips = peer.get("TailscaleIPs") or []
        devices.append({
            "name": short_name(peer),
            "host": peer.get("HostName", ""),
            "os": peer.get("OS", ""),
            "online": bool(peer.get("Online")),
            "ip": ips[0] if ips else "",
            # Taildrop only works to your own devices; shared-in devices have a different owner.
            "mine": peer.get("UserID") == self_peer.get("UserID"),
        })
    devices.sort(key=lambda d: (not d["online"], not d["mine"], d["name"].lower()))
    return {"me": me, "devices": devices}


def receive_files():
    """Pull any waiting Taildrop files into DOWNLOADS. Returns names of new files."""
    with RECEIVE_LOCK:
        os.makedirs(DOWNLOADS, exist_ok=True)
        before = set(os.listdir(DOWNLOADS))
        run_tailscale("file", "get", "--conflict=rename", DOWNLOADS, timeout=600)
        after = set(os.listdir(DOWNLOADS))
        return sorted(after - before)


def list_received():
    if not os.path.isdir(DOWNLOADS):
        return []
    files = []
    for name in os.listdir(DOWNLOADS):
        path = os.path.join(DOWNLOADS, name)
        if os.path.isfile(path) and not name.startswith("."):
            st = os.stat(path)
            files.append({"name": name, "size": st.st_size, "mtime": st.st_mtime})
    files.sort(key=lambda f: f["mtime"], reverse=True)
    return files


def open_path(path):
    system = platform.system()
    if system == "Windows":
        os.startfile(path)  # noqa: S606
    elif system == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# ---------------------------------------------------------------------- web ---

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self, query):
        # Only the page we served knows the token, so other websites can't drive this server.
        return secrets.compare_digest(self.headers.get("X-Token", ""), TOKEN) or \
            secrets.compare_digest(query.get("t", [""])[0], TOKEN)

    def _route(self, method):
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        if method == "GET" and url.path == "/icon.svg":
            # Public on purpose: browsers fetch favicons without our token, and it's just the logo.
            try:
                with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.svg"), "rb") as f:
                    return self._send(200, f.read(), "image/svg+xml")
            except OSError:
                return self._send(404, b"", "text/plain")
        if method == "GET" and url.path == "/":
            if not self._authorized(query):
                return self._send(403, b"Open FileShare from the link it printed.", "text/plain")
            page = PAGE.replace("__TOKEN__", TOKEN).encode()
            return self._send(200, page, "text/html; charset=utf-8")
        if not self._authorized(query):
            return self._send(403, {"error": "forbidden"})
        try:
            if method == "GET" and url.path == "/api/devices":
                return self._send(200, list_devices())
            if method == "GET" and url.path == "/api/received":
                return self._send(200, {"folder": DOWNLOADS, "files": list_received()})
            if method == "POST" and url.path == "/api/receive":
                return self._send(200, {"new": receive_files()})
            if method == "POST" and url.path == "/api/send":
                return self._send(200, self._handle_send(query))
            if method == "POST" and url.path == "/api/open":
                name = query.get("name", [""])[0]
                target = DOWNLOADS
                if name:
                    target = os.path.join(DOWNLOADS, os.path.basename(name))
                os.makedirs(DOWNLOADS, exist_ok=True)
                open_path(target)
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})
        except Exception as e:  # surface every failure to the UI
            return self._send(500, {"error": str(e)})

    def _handle_send(self, query):
        target = query.get("target", [""])[0]
        name = os.path.basename(query.get("name", ["file"])[0]) or "file"
        length = int(self.headers.get("Content-Length", "0"))
        if not target:
            raise RuntimeError("No device selected.")
        tmpdir = tempfile.mkdtemp(prefix="fileshare-")
        path = os.path.join(tmpdir, name)
        try:
            with open(path, "wb") as f:
                remaining = length
                while remaining > 0:
                    chunk = self.rfile.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
            run_tailscale("file", "cp", path, f"{target}:", timeout=24 * 3600)
            return {"ok": True, "name": name}
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")


def open_window(url):
    """Prefer a chromeless app window (Chrome/Edge/Chromium), fall back to the default browser."""
    system = platform.system()
    candidates = []
    if system == "Windows":
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                     os.environ.get("LOCALAPPDATA")):
            if base:
                candidates += [
                    os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                    os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                ]
    elif system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    else:
        candidates = [shutil.which(n) for n in
                      ("google-chrome", "chromium", "chromium-browser", "microsoft-edge")]
    for exe in candidates:
        if exe and os.path.isfile(exe):
            try:
                subprocess.Popen([exe, f"--app={url}", "--window-size=900,700"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                pass
    webbrowser.open(url)


def main():
    global DOWNLOADS, TAILSCALE
    parser = argparse.ArgumentParser(description="Drag-and-drop file sharing over Tailscale.")
    parser.add_argument("--downloads", default=os.path.join(os.path.expanduser("~"), "Downloads", "FileShare"))
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    DOWNLOADS = os.path.abspath(os.path.expanduser(args.downloads))
    TAILSCALE = find_tailscale()
    if not TAILSCALE:
        print("Warning: couldn't find the tailscale command; the app will show an error.")

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={TOKEN}"
    print(f"FileShare is running at {url}")
    print(f"Received files go to {DOWNLOADS}")
    print("Press Ctrl+C to quit.")
    if not args.no_open:
        threading.Timer(0.3, open_window, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


# --------------------------------------------------------------------- page ---

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FileShare</title>
<link rel="icon" type="image/svg+xml" href="/icon.svg">
<style>
  :root {
    --bg: #f6f7f9; --panel: #ffffff; --text: #1d2330; --muted: #6b7385; --line: #e3e6ec;
    --accent: #3b6cf6; --accent-soft: #e8eefe; --ok: #1f9d55; --err: #d64545;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #14161b; --panel: #1c1f26; --text: #e7e9ee; --muted: #9098a9; --line: #2c313b;
      --accent: #6d92ff; --accent-soft: #232c45; --ok: #4cc38a; --err: #ff7272;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
         background: var(--bg); color: var(--text); }
  header { display: flex; align-items: center; gap: 12px; padding: 14px 20px;
           border-bottom: 1px solid var(--line); background: var(--panel); }
  header h1 { font-size: 16px; margin: 0; }
  header img { width: 28px; height: 28px; border-radius: 7px; flex: none; }
  header .me { color: var(--muted); font-size: 13px; }
  main { display: grid; grid-template-columns: 260px 1fr; gap: 16px; padding: 16px 20px; }
  @media (max-width: 680px) { main { grid-template-columns: 1fr; } }
  section { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 14px; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted);
       margin: 0 0 10px; display: flex; justify-content: space-between; align-items: center; }
  button { font: inherit; border: 1px solid var(--line); background: var(--panel); color: var(--text);
           border-radius: 6px; padding: 4px 10px; cursor: pointer; }
  button:hover { border-color: var(--accent); }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  .devices { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
  .devices li { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 8px;
                cursor: pointer; border: 1px solid transparent; }
  .devices li:hover { background: var(--accent-soft); }
  .devices li.sel { background: var(--accent-soft); border-color: var(--accent); }
  .devices li.off { opacity: .5; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); flex: none; }
  .on .dot { background: var(--ok); }
  .devices .os { margin-left: auto; color: var(--muted); font-size: 12px; }
  .right { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
  #drop { border: 2px dashed var(--line); border-radius: 10px; padding: 40px 16px; text-align: center;
          color: var(--muted); cursor: pointer; transition: all .15s; }
  #drop.over { border-color: var(--accent); background: var(--accent-soft); color: var(--text); }
  #drop strong { color: var(--text); display: block; font-size: 16px; margin-bottom: 4px; }
  .list { list-style: none; margin: 0; padding: 0; }
  .list li { display: flex; gap: 10px; align-items: center; padding: 6px 2px; border-top: 1px solid var(--line); }
  .list li:first-child { border-top: none; }
  .list .name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .list .meta { color: var(--muted); font-size: 12px; white-space: nowrap; }
  .ok { color: var(--ok); } .err { color: var(--err); white-space: pre-wrap; }
  .muted { color: var(--muted); }
  .bar { height: 4px; background: var(--line); border-radius: 2px; overflow: hidden; width: 90px; }
  .bar > i { display: block; height: 100%; background: var(--accent); width: 0; }
  label.auto { font-size: 12px; color: var(--muted); text-transform: none; letter-spacing: 0;
               display: flex; gap: 4px; align-items: center; }
  #banner { margin: 16px 20px 0; padding: 10px 14px; border-radius: 8px; display: none;
            background: var(--accent-soft); border: 1px solid var(--err); }
</style>
</head>
<body>
<header>
  <img src="/icon.svg" alt="">
  <h1>FileShare</h1>
  <span class="me" id="me"></span>
</header>
<div id="banner" class="err"></div>
<main>
  <section>
    <h2>Devices <button id="refresh" title="Refresh devices">&#x21bb;</button></h2>
    <ul class="devices" id="devices"><li class="muted">Loading…</li></ul>
  </section>
  <div class="right">
    <section>
      <h2>Send</h2>
      <div id="drop"><strong>Drop files here</strong><span id="dropHint">Pick a device first</span></div>
      <input type="file" id="picker" multiple hidden>
      <ul class="list" id="sends"></ul>
    </section>
    <section>
      <h2>
        <span>Received</span>
        <span style="display:flex; gap:8px; align-items:center">
          <label class="auto"><input type="checkbox" id="auto" checked> auto-check</label>
          <button id="check" class="primary">Check now</button>
          <button id="folder">Open folder</button>
        </span>
      </h2>
      <div class="muted" id="recvStatus"></div>
      <ul class="list" id="received"></ul>
    </section>
  </div>
</main>
<script>
const TOKEN = "__TOKEN__";
let selected = null;
let checking = false;

const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmtSize = n => n < 1024 ? n + " B" : n < 1048576 ? (n/1024).toFixed(1) + " KB"
  : n < 1073741824 ? (n/1048576).toFixed(1) + " MB" : (n/1073741824).toFixed(2) + " GB";

async function api(method, path, params = {}) {
  const q = new URLSearchParams(params).toString();
  const r = await fetch(path + (q ? "?" + q : ""), { method, headers: { "X-Token": TOKEN } });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

function banner(msg) {
  $("banner").textContent = msg || "";
  $("banner").style.display = msg ? "block" : "none";
}

async function loadDevices() {
  try {
    const { me, devices } = await api("GET", "/api/devices");
    banner("");
    $("me").textContent = me ? "on " + me : "";
    const ul = $("devices");
    if (!devices.length) { ul.innerHTML = '<li class="muted">No other devices on your tailnet.</li>'; return; }
    ul.innerHTML = "";
    for (const d of devices) {
      const li = document.createElement("li");
      li.className = (d.online ? "on" : "off") + (selected === d.name ? " sel" : "");
      li.title = d.mine ? (d.ip + (d.online ? "" : " (offline)")) : "Shared with you: Taildrop only sends to your own devices";
      li.innerHTML = `<span class="dot"></span><span>${esc(d.name)}</span><span class="os">${esc(d.os)}</span>`;
      li.onclick = () => { selected = d.name; updateHint(); loadDevicesFromCache(); };
      li.dataset.name = d.name;
      ul.appendChild(li);
    }
    updateHint();
  } catch (e) { banner(e.message); $("devices").innerHTML = '<li class="muted">Couldn\'t load devices.</li>'; }
}
function loadDevicesFromCache() {
  for (const li of $("devices").children) li.classList.toggle("sel", li.dataset.name === selected);
}
function updateHint() {
  $("dropHint").textContent = selected ? `to ${selected} (or click to choose)` : "Pick a device first";
}

function sendFile(file) {
  const target = selected;
  const li = document.createElement("li");
  li.innerHTML = `<span class="name">${esc(file.name)}</span><span class="meta">${fmtSize(file.size)} → ${esc(target)}</span><span class="bar"><i></i></span>`;
  $("sends").prepend(li);
  const bar = li.querySelector("i");
  const status = li.querySelector(".bar");
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/send?" + new URLSearchParams({ target, name: file.name }));
  xhr.setRequestHeader("X-Token", TOKEN);
  xhr.upload.onprogress = e => { if (e.lengthComputable) bar.style.width = (e.loaded / e.total * 100) + "%"; };
  xhr.upload.onload = () => { status.outerHTML = '<span class="meta">sending…</span>'; };
  xhr.onload = () => {
    let data = {}; try { data = JSON.parse(xhr.responseText); } catch {}
    const last = li.lastElementChild;
    if (xhr.status === 200) { last.outerHTML = '<span class="meta ok">sent ✓</span>'; }
    else { last.outerHTML = `<span class="meta err" title="${esc(data.error || "")}">failed</span>`;
           banner(`Couldn't send ${file.name}: ${data.error || xhr.statusText}`); }
  };
  xhr.onerror = () => { li.lastElementChild.outerHTML = '<span class="meta err">failed</span>'; };
  xhr.send(file);
}

function handleFiles(files) {
  if (!selected) { banner("Pick a device on the left first."); return; }
  banner("");
  for (const f of files) sendFile(f);
}

const drop = $("drop");
["dragenter", "dragover"].forEach(ev => document.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(ev => document.addEventListener(ev, e => { e.preventDefault(); if (ev === "drop" || !e.relatedTarget) drop.classList.remove("over"); }));
document.addEventListener("drop", e => {
  const files = [...e.dataTransfer.files];
  if (files.length) handleFiles(files);
});
drop.onclick = () => { if (!selected) { banner("Pick a device on the left first."); return; } $("picker").click(); };
$("picker").onchange = e => { handleFiles([...e.target.files]); e.target.value = ""; };

async function loadReceived(highlight = []) {
  try {
    const { folder, files } = await api("GET", "/api/received");
    $("recvStatus").textContent = files.length ? "" : `Nothing yet. Files are saved to ${folder}`;
    const ul = $("received");
    ul.innerHTML = "";
    for (const f of files.slice(0, 50)) {
      const li = document.createElement("li");
      const isNew = highlight.includes(f.name);
      li.innerHTML = `<span class="name">${isNew ? '<b class="ok">new</b> ' : ""}${esc(f.name)}</span>
        <span class="meta">${fmtSize(f.size)} · ${new Date(f.mtime * 1000).toLocaleString()}</span>`;
      const btn = document.createElement("button"); btn.textContent = "Open";
      btn.onclick = () => api("POST", "/api/open", { name: f.name }).catch(e => banner(e.message));
      li.appendChild(btn);
      ul.appendChild(li);
    }
  } catch (e) { banner(e.message); }
}

async function checkIncoming(manual) {
  if (checking) return;
  checking = true;
  if (manual) $("recvStatus").textContent = "Checking…";
  try {
    const { new: got } = await api("POST", "/api/receive");
    await loadReceived(got);
    if (got.length) {
      document.title = `(${got.length}) FileShare`;
      setTimeout(() => document.title = "FileShare", 5000);
    } else if (manual && !$("received").children.length) {
      $("recvStatus").textContent = "No new files.";
    }
  } catch (e) { if (manual) banner(e.message); else $("recvStatus").textContent = e.message; }
  checking = false;
}

$("refresh").onclick = loadDevices;
$("check").onclick = () => checkIncoming(true);
$("folder").onclick = () => api("POST", "/api/open").catch(e => banner(e.message));

loadDevices();
loadReceived().then(() => checkIncoming(false));
setInterval(() => { if ($("auto").checked) checkIncoming(false); }, 5000);
setInterval(loadDevices, 30000);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
