#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LAN Share — offline multi-device file/folder transfer over LAN.

Run:      python lanshare.py
Options:  --port 8765   --dir Received   --fix-firewall (admin)

Host device (PC ya Termux phone) par chalta hai. Baaki devices QR scan
karke browser mein khulte hain — koi app install nahi.
"""
import argparse
import asyncio
import json
import os
import queue
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

from aiohttp import web, WSMsgType
import segno

BASE = Path(__file__).resolve().parent
VERSION = "0.3.0"

# ------------------------------------------------------------------ state
TOKEN = secrets.token_urlsafe(18)
DEVICES = {}    # sid -> {name, os, ws, joined, addr}
TRANSFERS = {}  # tid -> {name, relpath, size, batch, sender, recipients,
                #          received, path, done, done_at}
RECV_DIR = BASE / "Received"
_PORT = 8765


# ------------------------------------------------------------------ network
def _is_lan(ip: str) -> bool:
    if not re.match(r"^\d+\.\d+\.\d+\.\d+$", ip):
        return False
    if ip.startswith(("127.", "169.254.")):
        return False
    if ip.startswith("192.168.") or ip.startswith("10."):
        return True
    if ip.startswith("172."):
        try:
            return 16 <= int(ip.split(".")[1]) <= 31
        except ValueError:
            return False
    return False


def lan_ipv4s():
    """Return (primary_ip, [all_lan_ips]) — WSL/VirtualBox adapters last."""
    found = {}

    # 1. default-route trick -> sabse bharosemand IP
    primary = ""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 80))
        primary = s.getsockname()[0]
        s.close()
    except OSError:
        pass
    if primary and _is_lan(primary):
        found[primary] = "Default Route (Wi-Fi/Hotspot)"

    # 2. hostname resolution
    try:
        for fam, _, _, _, sa in socket.getaddrinfo(
                socket.gethostname(), None, socket.AF_INET):
            ip = sa[0]
            if _is_lan(ip):
                found.setdefault(ip, "Hostname Adapter")
    except OSError:
        pass

    # 3. Windows ipconfig — adapter names capture karke prefer Wi-Fi/Ethernet
    if sys.platform.startswith("win"):
        try:
            out = subprocess.run(["ipconfig"], capture_output=True,
                                 text=True, timeout=5).stdout
            adapter = ""
            for line in out.splitlines():
                s = line.strip()
                if s and not line.startswith((" ", "\t")) and s.endswith(":"):
                    adapter = s
                m = re.search(r"IPv4[^:]*:\s*([\d\.]+)", line)
                if m and _is_lan(m.group(1)):
                    found.setdefault(
                        m.group(1),
                        adapter[:60] if adapter else "Adapter")
        except Exception:
            pass

    ips = list(found.keys())

    def rank(ip):
        pref = {primary: 0}.get(ip, 1)
        kind = (0 if ip.startswith("192.168.") else
                1 if ip.startswith("10.") else 2)
        virt = 1 if ip.startswith("172.") else 0   # WSL/docker aakhir mein
        return (pref, kind, virt)

    ips.sort(key=rank)
    return primary or (ips[0] if ips else "127.0.0.1"), \
        [(ip, found[ip]) for ip in ips]


def print_qr_terminal(url):
    """Terminal QR — bina ANSI codes ke, Unicode half-blocks se.
    segno.terminal() Windows cmd par escape-code garbage deta hai;
    ye printer har console mein sahi chhapta hai (width ~42 cols)."""
    qr = segno.make(url, error="m")
    m = [list(row) for row in qr.matrix]
    pad = 2  # quiet zone
    w = len(m[0]) + pad * 2
    empty = [False] * w
    rows = [[False] * w for _ in range(pad)]
    for row in m:
        rows.append([False] * pad + row + [False] * pad)
    rows += [[False] * w for _ in range(pad)]

    print()
    for y in range(0, len(rows), 2):
        top = rows[y]
        bot = rows[y + 1] if y + 1 < len(rows) else empty
        line = "".join("\u2588" if a and b else "\u2580" if a else
                       "\u2584" if b else " "
                       for a, b in zip(top, bot))
        print("  " + line)
    print()


def fix_firewall(port):
    if not sys.platform.startswith("win"):
        return
    rule = "LAN Share (port %d)" % port
    cmd = ["netsh", "advfirewall", "firewall", "add", "rule",
           f"name={rule}", "dir=in", "action=allow", "protocol=TCP",
           "localport", str(port)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            print(f"  [firewall] allow rule added: {rule}")
        else:
            print("  [firewall] add nahi hua (admin se chalao). Manual:")
            print("    " + " ".join(cmd))
    except Exception as e:
        print(f"  [firewall] error: {e}")


# ------------------------------------------------------------------ helpers
def authed(request) -> bool:
    tok = request.query.get("token") or \
        request.cookies.get("lsid") or \
        request.headers.get("X-LS-Token")
    return secrets.compare_digest(str(tok), TOKEN)


def require_auth(handler):
    async def wrapped(request):
        if not authed(request):
            return web.Response(status=403, text="Invalid/expired session token.")
        return await handler(request)
    return wrapped


def safe_relpath(p: str) -> str:
    p = (p or "file").replace("\\", "/")
    parts = [x for x in p.split("/") if x not in ("", ".", "..")]
    return "/".join(parts) or "file"


def broadcast_now(target_sids, payload: dict):
    """Async context mein seedha bhejo."""
    msg = json.dumps(payload)
    for sid, dev in list(DEVICES.items()):
        if target_sids != "all" and sid not in target_sids:
            continue
        ws = dev.get("ws")
        if ws and not ws.closed:
            asyncio.ensure_future(ws.send_str(msg))


# ------------------------------------------------------------------ app
app = web.Application(client_max_size=128 * 1024 * 1024)  # 4MB chunks + headroom
app["last_progress"] = {}


async def index(request):
    if not authed(request):
        return web.Response(status=403, text=(
            "<h2 style='font-family:sans-serif'>Session expired / galat link.</h2>"
            "<p>QR dobara scan karo ya host se naya URL lo.</p>"))
    resp = web.Response(text=HTML, content_type="text/html")
    resp.set_cookie("lsid", TOKEN, path="/", samesite="Lax")
    return resp


@require_auth
async def api_info(request):
    primary, ips = lan_ipv4s()
    return web.json_response({
        "version": VERSION,
        "port": _PORT,
        "primary": primary,
        "ips": [{"ip": ip, "label": lbl} for ip, lbl in ips],
        "devices": len(DEVICES) + 1,
    })


@require_auth
async def qr_svg(request):
    ip = request.query.get("ip") or lan_ipv4s()[0]
    url = f"http://{ip}:{_PORT}/?token={TOKEN}"
    qr = segno.make(url, error="m")
    svg = qr.svg_inline(border=2, unit=4)
    return web.Response(text=svg, content_type="image/svg+xml")


@require_auth
async def url_list(request):
    primary, ips = lan_ipv4s()
    return web.json_response({
        "primary": primary,
        "urls": [f"http://{ip}:{_PORT}/?token={TOKEN}" for ip, _ in ips],
    })


# ------------------------------------------------------------------ websocket
async def ws_handler(request):
    if not authed(request):
        raise web.HTTPForbidden(text="bad token")
    ws = web.WebSocketResponse(heartbeat=25)
    await ws.prepare(request)
    sid = None
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            ev = data.get("ev")
            if ev == "hello":
                sid = str(data.get("sid") or secrets.token_hex(6))
                DEVICES[sid] = {
                    "name": str(data.get("name", "Device"))[:40],
                    "os": str(data.get("os", ""))[:30],
                    "ws": ws, "joined": time.time(),
                    "addr": request.remote,
                }
                broadcast_now("all", _devices_payload())
                await ws.send_str(json.dumps({"ev": "welcome", "sid": sid}))
            elif ev == "rename" and sid in DEVICES:
                DEVICES[sid]["name"] = str(data.get("name", "Device"))[:40]
                broadcast_now("all", _devices_payload())
    finally:
        if sid and DEVICES.get(sid, {}).get("ws") is ws:
            DEVICES.pop(sid, None)
            broadcast_now("all", _devices_payload())
    return ws


def _devices_payload():
    now = time.time()
    devs = [{"sid": s, "name": d["name"], "os": d["os"],
             "since": int(now - d["joined"])}
            for s, d in DEVICES.items() if d.get("ws") and not d["ws"].closed]
    return {"ev": "devices", "devices": devs, "count": len(devs) + 1}


# ------------------------------------------------------------------ uploads
@require_auth
async def upload_start(request):
    body = await request.json()
    name = os.path.basename(str(body.get("name", "file")))[:180] or "file"
    relpath = safe_relpath(body.get("relpath") or name)
    size = max(0, int(body.get("size", 0)))
    batch = safe_relpath(str(body.get("batch", secrets.token_hex(6))))
    sender = str(body.get("sid", ""))
    recipients = body.get("recipients", "all")
    if isinstance(recipients, list):
        recipients = {str(r) for r in recipients if r != sender} or "all"

    tid = secrets.token_hex(8)
    dest_dir = RECV_DIR / batch
    dest = dest_dir / relpath
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"")

    TRANSFERS[tid] = {
        "name": name, "relpath": relpath, "size": size, "batch": batch,
        "sender": sender, "recipients": recipients, "received": 0,
        "path": dest, "done": False, "done_at": None, "started": time.time(),
    }
    return web.json_response({"id": tid})


@require_auth
async def upload_chunk(request):
    tid = request.query.get("id", "")
    t = TRANSFERS.get(tid)
    if not t or t["done"]:
        raise web.HTTPNotFound(text="unknown transfer")
    data = await request.read()
    loop = asyncio.get_running_loop()
    # executor mein disk-write taaki event-loop block na ho
    await loop.run_in_executor(None, _append, t["path"], data)
    t["received"] += len(data)

    now = time.time()
    key = now
    last = app["last_progress"].get(tid, 0)
    if now - last > 0.25:
        app["last_progress"][tid] = now
        sender = DEVICES.get(t["sender"])
        if sender and sender.get("ws") and not sender["ws"].closed:
            await sender["ws"].send_str(json.dumps({
                "ev": "progress", "id": tid,
                "received": t["received"], "size": t["size"]}))
    return web.json_response({"ok": True, "received": t["received"]})


def _append(path: Path, data: bytes):
    with open(path, "ab") as f:
        f.write(data)


@require_auth
async def upload_end(request):
    tid = request.query.get("id", "")
    t = TRANSFERS.get(tid)
    if not t:
        raise web.HTTPNotFound(text="unknown transfer")
    t["done"] = True
    t["done_at"] = time.time()
    app["last_progress"].pop(tid, None)

    sender = DEVICES.get(t["sender"])
    if sender and sender.get("ws") and not sender["ws"].closed:
        await sender["ws"].send_str(json.dumps({
            "ev": "done", "id": tid, "name": t["name"]}))

    meta = {"ev": "incoming", "id": tid, "name": t["name"],
            "relpath": t["relpath"], "size": t["size"],
            "batch": t["batch"],
            "from": sender["name"] if sender else "unknown"}
    broadcast_now(t["recipients"], meta)
    return web.json_response({"ok": True})


# ------------------------------------------------------------------ downloads
@require_auth
async def api_files(request):
    items = []
    for tid, t in TRANSFERS.items():
        if not t["done"]:
            continue
        sender = DEVICES.get(t["sender"])
        items.append({
            "id": tid, "name": t["name"], "relpath": t["relpath"],
            "size": t["size"], "batch": t["batch"],
            "from": sender["name"] if sender else "device",
            "at": t["done_at"] or time.time(),
        })
    items.sort(key=lambda x: x["at"])
    return web.json_response({"files": items})


@require_auth
async def download(request):
    tid = request.query.get("id", "")
    t = TRANSFERS.get(tid)
    if not t or not t["done"] or not t["path"].exists():
        raise web.HTTPNotFound(text="file not found")
    fname = re.sub(r'[\\/:*?"<>|]', "_", t["name"])
    return web.FileResponse(
        t["path"],
        headers={"Content-Disposition":
                 f"attachment; filename=\"{fname}\"",
                 "Cache-Control": "no-store"})


class _QStream:
    """zipfile ke liye blocking, unseekable sink -> asyncio queue."""

    def __init__(self, q):
        self.q = q
        self.pos = 0

    def write(self, data):
        self.q.put(bytes(data))
        self.pos += len(data)

    def flush(self):
        pass

    def tell(self):
        return self.pos

    def seekable(self):
        return False

    def writable(self):
        return True


@require_auth
async def download_zip(request):
    batch = safe_relpath(request.query.get("batch", ""))
    items = [t for t in TRANSFERS.values()
             if t["batch"] == batch and t["done"] and t["path"].exists()]
    if not items:
        raise web.HTTPNotFound(text="empty batch")
    zipname = re.sub(r'[\\/:*?"<>|]', "_",
                     Path(items[0]["relpath"]).parts[0]
                     if len(Path(items[0]["relpath"]).parts) > 1
                     else items[0]["name"]) + ".zip"

    q = queue.Queue(maxsize=16)

    def producer():
        try:
            stream = _QStream(q)
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_STORED,
                                 allowZip64=True) as zf:
                for t in items:
                    zi = zipfile.ZipInfo(t["relpath"])
                    zi.compress_type = zipfile.ZIP_STORED
                    zi.external_attr = 0o644 << 16
                    with zf.open(zi, "w", force_zip64=True) as dst, \
                            open(t["path"], "rb") as src:
                        shutil.copyfileobj(src, dst, 1 << 20)
            q.put(None)
        except Exception as e:  # noqa
            q.put(e)

    resp = web.StreamResponse(headers={
        "Content-Disposition":
            f"attachment; filename=\"{zipname}\"",
        "Cache-Control": "no-store",
    })
    await resp.prepare(request)
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, producer)
    try:
        while True:
            item = await loop.run_in_executor(None, q.get)
            if item is None:
                break
            if isinstance(item, Exception):
                break
            await resp.write(item)
    finally:
        await resp.write_eof()
    return resp


@require_auth
async def api_wipe(request):
    for f in RECV_DIR.iterdir() if RECV_DIR.exists() else []:
        try:
            if f.is_dir():
                shutil.rmtree(f, ignore_errors=True)
            else:
                f.unlink(missing_ok=True)
        except OSError:
            pass
    TRANSFERS.clear()
    app["last_progress"].clear()
    broadcast_now("all", {"ev": "wiped"})
    return web.json_response({"ok": True})


app.router.add_get("/", index)
app.router.add_get("/api/info", api_info)
app.router.add_get("/qr", qr_svg)
app.router.add_get("/api/urls", url_list)
app.router.add_get("/ws", ws_handler)
app.router.add_post("/api/upload/start", upload_start)
app.router.add_post("/api/upload/chunk", upload_chunk)
app.router.add_post("/api/upload/end", upload_end)
app.router.add_get("/api/files", api_files)
app.router.add_get("/api/dl", download)
app.router.add_get("/api/dlzip", download_zip)
app.router.add_post("/api/wipe", api_wipe)


# ------------------------------------------------------------------ HTML
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LAN Share</title>
<link rel="icon" href="data:,">
<style>
:root{
  --bg:#0b0f14;--card:#131a22;--card2:#1a232e;--acc:#22d3ee;--acc2:#34d399;
  --txt:#e6edf3;--mut:#7d8b99;--bad:#f87171;--warn:#fbbf24;
  --r:14px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:radial-gradient(1200px 700px at 80% -10%,#123040 0%,var(--bg) 55%);
  color:var(--txt);font-family:system-ui,Segoe UI,Roboto,sans-serif;
  min-height:100vh;padding:16px;
}
.wrap{max-width:860px;margin:0 auto}
header{display:flex;align-items:center;gap:10px;margin-bottom:18px}
.logo{font-size:20px;font-weight:800;letter-spacing:.3px}
.logo span{color:var(--acc)}
.pill{margin-left:auto;font-size:12px;color:var(--mut);display:flex;align-items:center;gap:6px}
.dot{width:9px;height:9px;border-radius:50%;background:var(--bad);display:inline-block}
.dot.on{background:var(--acc2);box-shadow:0 0 8px var(--acc2)}
.screen{display:none}
.screen.active{display:block}
.card{
  background:var(--card);border:1px solid #212d3a;border-radius:var(--r);
  padding:18px;margin-bottom:14px;
}
.qrbox{display:flex;gap:18px;flex-wrap:wrap;align-items:center}
.qrbox .qr{background:#fff;padding:10px;border-radius:12px;line-height:0}
.qrbox .qr svg{width:180px;height:180px}
.urls{flex:1;min-width:240px}
.urls code{
  display:block;background:#0a0e12;border:1px solid #223040;border-radius:8px;
  padding:8px 10px;margin:6px 0;font-size:12px;word-break:break-all;color:var(--acc)
}
select,input[type=text]{
  background:var(--card2);border:1px solid #2a3a4a;color:var(--txt);
  border-radius:10px;padding:9px 10px;font-size:13px;width:100%;
}
.count{
  font-size:52px;font-weight:800;color:var(--acc);text-align:center;line-height:1.1
}
.count-sub{text-align:center;color:var(--mut);margin:2px 0 14px;font-size:14px}
.dev{
  display:flex;align-items:center;gap:12px;padding:11px 12px;
  background:var(--card2);border:1px solid #263444;border-radius:12px;margin-bottom:8px;
  cursor:pointer;transition:.15s;user-select:none
}
.dev:hover{border-color:var(--acc)}
.dev.sel{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc) inset;background:#122430}
.dev .av{
  width:38px;height:38px;border-radius:10px;display:flex;align-items:center;
  justify-content:center;font-weight:800;font-size:16px;color:#04121a;flex:none
}
.dev .nm{font-weight:600;font-size:15px}
.dev .sub{font-size:12px;color:var(--mut)}
.dev .tick{margin-left:auto;color:var(--acc);font-size:20px;opacity:0;transition:.15s}
.dev.sel .tick{opacity:1}
.btnrow{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}
button{
  background:var(--acc);color:#04121a;border:0;border-radius:12px;
  padding:12px 18px;font-size:15px;font-weight:700;cursor:pointer;transition:.15s
}
button:hover{filter:brightness(1.1)}
button:disabled{opacity:.35;cursor:not-allowed}
button.sec{background:var(--card2);color:var(--txt);border:1px solid #2a3a4a}
button.warn{background:#3b1418;color:var(--bad);border:1px solid #5b2027}
button.big{width:100%;font-size:17px;padding:15px}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.chip{
  background:#10313a;color:var(--acc);border:1px solid #17505e;border-radius:999px;
  padding:5px 12px;font-size:13px;display:flex;gap:6px;align-items:center
}
.chip b{cursor:pointer;opacity:.7}
.drop{
  border:2px dashed #2c4256;border-radius:var(--r);padding:34px 16px;text-align:center;
  color:var(--mut);transition:.15s;background:var(--card)
}
.drop.over{border-color:var(--acc);color:var(--acc);background:#0f2129}
.tcard{background:var(--card2);border:1px solid #263444;border-radius:12px;padding:12px;margin-top:10px}
.trow{display:flex;justify-content:space-between;font-size:13px;margin-bottom:7px;gap:8px}
.tname{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tsub{color:var(--mut);font-size:12px;flex:none}
.bar{height:8px;border-radius:99px;background:#0a0e12;overflow:hidden}
.bar>i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--acc),var(--acc2));transition:.2s}
h3{font-size:15px;margin:16px 0 8px;color:var(--txt)}
.frow{
  display:flex;align-items:center;gap:10px;background:var(--card2);
  border:1px solid #263444;border-radius:12px;padding:10px 12px;margin-bottom:8px;flex-wrap:wrap
}
.frow .fn{font-size:14px;font-weight:600;flex:1;min-width:140px;word-break:break-all}
.frow .fs{font-size:12px;color:var(--mut)}
.frow .ff{font-size:12px;color:var(--acc2)}
.dl{background:#0f3a2c;color:var(--acc2);border:1px solid #17664c;border-radius:9px;
    padding:7px 12px;font-size:13px;font-weight:700;cursor:pointer}
.tip{font-size:12.5px;color:var(--warn);background:#2a210c;border:1px solid #4d3c12;
     border-radius:10px;padding:10px 12px;margin-top:10px}
.mut{color:var(--mut);font-size:13px}
.back{background:none;border:0;color:var(--mut);font-size:14px;cursor:pointer;padding:4px 0;margin-bottom:10px}
#hostpanel{display:none}
#hostpanel.show{display:block}
#toasts{position:fixed;bottom:16px;right:16px;display:flex;flex-direction:column;gap:8px;z-index:99}
.toast{background:var(--card);border:1px solid var(--acc);border-radius:12px;
       padding:11px 14px;font-size:13.5px;box-shadow:0 8px 24px #0008;max-width:320px}
input[type=file]{display:none}
@media (max-width:520px){.qrbox .qr svg{width:140px;height:140px}.count{font-size:42px}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo">⚡ LAN<span>Share</span></div>
    <div class="pill"><span class="dot" id="dot"></span><span id="netstat">connecting…</span></div>
  </header>

  <!-- ============ HOST PANEL (QR) ============ -->
  <div id="hostpanel">
    <div class="card">
      <div class="qrbox">
        <div class="qr" id="qr"></div>
        <div class="urls">
          <b style="font-size:15px">Scan karo → browser khulega</b>
          <div class="mut" style="margin:4px 0 8px">Har device is URL par khulega. Incognito chahiye to URL incognito tab mein paste karo.</div>
          <select id="ipdrop" style="margin-bottom:8px"></select>
          <code id="urltext">…</code>
          <div class="btnrow" style="margin-top:4px">
            <button class="sec" onclick="copyUrl()">📋 Copy URL</button>
            <button class="sec" onclick="loadQR()">🔄 New QR</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- ============ SCREEN 1: DEVICES ============ -->
  <section id="s1" class="screen active">
    <div class="card">
      <div class="count" id="devCount">1</div>
      <div class="count-sub">devices is connection par connected</div>
      <div id="devList"></div>
      <div class="mut" id="devHint" style="text-align:center">Baaki devices QR scan karke judenge…</div>
      <div class="btnrow">
        <button class="big" id="btnAll" disabled>📤 Sabhi devices pe bhejo</button>
      </div>
      <div class="btnrow">
        <button class="big sec" id="btnNext" disabled>Selected devices chuno →</button>
      </div>
    </div>
  </section>

  <!-- ============ SCREEN 2: SEND ============ -->
  <section id="s2" class="screen">
    <button class="back" onclick="go(1)">← Wapas device list</button>
    <div class="card">
      <h3 style="margin-top:0">Bhejne ke liye chuno</h3>
      <div class="chips" id="chips"></div>
      <div class="btnrow" style="margin-top:0">
        <button onclick="fFiles.click()">🗂 Files</button>
        <button onclick="fFolder.click()">📁 Folder</button>
        <button class="sec" onclick="fFolderMulti.click()">📂 Multiple Folders</button>
      </div>
      <input type="file" id="fFiles" multiple onchange="pickFiles(this.files)">
      <input type="file" id="fFolder" webkitdirectory onchange="pickFiles(this.files)">
      <input type="file" id="fFolderMulti" webkitdirectory multiple onchange="pickFiles(this.files)">
      <div class="drop" id="drop" style="margin-top:12px">
        ya yahan <b>drag & drop</b> karo (files/folders dono chalte hain)
      </div>
      <div id="prog"></div>
    </div>
    <div class="card">
      <h3 style="margin-top:0">📥 Received files</h3>
      <div id="files"></div>
      <div class="mut" id="nofiles">abhi kuch nahi aaya</div>
      <div class="btnrow">
        <button class="sec" onclick="refreshFiles()">🔄 Refresh</button>
        <button class="warn" id="btnWipe" style="display:none" onclick="wipe()">🗑 Wipe Session</button>
      </div>
    </div>
  </section>
</div>
<div id="toasts"></div>

<script>
'use strict';
const $=s=>document.querySelector(s);
const HOST=(location.hash==='#host'||new URLSearchParams(location.search).get('host')==='1');
const SID=sessionStorage.getItem('lsid')||(crypto.randomUUID?crypto.randomUUID():Math.random().toString(36).slice(2));
sessionStorage.setItem('lsid',SID);
let isHost=HOST;
let devs=[],sel=new Set(),ws,retry=0,dlQueue=Promise.resolve(),lastCount=null;

/* ---------- device identity ---------- */
function guessOS(){
  const u=navigator.userAgent;
  if(/Android/i.test(u))return['📱','Android Phone','#34d399'];
  if(/iPhone|iPad/i.test(u))return['📱','iOS Device','#a78bfa'];
  if(/Windows/i.test(u))return['💻','Windows PC','#22d3ee'];
  if(/Macintosh/i.test(u))return['💻','Mac','#f59e0b'];
  if(/Linux/i.test(u))return['🐧','Linux','#fb7185'];
  return['❔','Device','#94a3b8'];
}
let [OSICON,OSNAME,OSCOL]=guessOS();
let myName=sessionStorage.getItem('lsname')||
  OSNAME+' '+(Math.floor(Math.random()*90)+10);
sessionStorage.setItem('lsname',myName);

/* ---------- websocket ---------- */
function connect(){
  const proto=location.protocol==='https:'?'wss:':'ws';
  ws=new WebSocket(proto+'://'+location.host+'/ws');
  ws.onopen=()=>{
    retry=0;$('#dot').classList.add('on');$('#netstat').textContent='connected';
    ws.send(JSON.stringify({ev:'hello',sid:SID,name:myName,os:OSNAME}));
  };
  ws.onclose=()=>{
    $('#dot').classList.remove('on');$('#netstat').textContent='reconnecting…';
    setTimeout(connect,Math.min(1000*2**retry++,8000));
  };
  ws.onmessage=e=>{
    const m=JSON.parse(e.data);
    if(m.ev==='devices'){devs=m.devices;renderDevices(m.count);}
    else if(m.ev==='incoming'){onIncoming(m);}
    else if(m.ev==='progress'){}
    else if(m.ev==='done'){}
    else if(m.ev==='wiped'){refreshFiles();toast('🧹 Session wiped — sab files delete');}
  };
}
connect();

/* ---------- screen 1: devices ---------- */
function renderDevices(count){
  $('#devCount').textContent=count;
  const others=devs.filter(d=>d.sid!==SID);
  const list=$('#devList');list.innerHTML='';
  others.forEach(d=>{
    const el=document.createElement('div');
    el.className='dev'+(sel.has(d.sid)?' sel':'');
    const hue=[...d.sid].reduce((a,c)=>a+c.charCodeAt(0),0)%360;
    el.innerHTML=`<div class="av" style="background:hsl(${hue} 70% 55%)">${(d.name[0]||'?').toUpperCase()}</div>
      <div><div class="nm">${esc(d.name)}</div><div class="sub">${esc(d.os)} · connected ${fmtDur(d.since)}</div></div>
      <div class="tick">✔</div>`;
    el.onclick=()=>{sel.has(d.sid)?sel.delete(d.sid):sel.add(d.sid);renderDevices(count);};
    list.appendChild(el);
  });
  $('#devHint').style.display=others.length?'none':'block';
  $('#btnAll').disabled=!others.length;
  $('#btnNext').disabled=!sel.size;
}
$('#btnAll').onclick=()=>{
  sel=new Set(devs.map(d=>d.sid).filter(s=>s!==SID));
  go(2);
};
$('#btnNext').onclick=()=>go(2);

function go(n){
  document.querySelectorAll('.screen').forEach(s=>s.classList.remove('active'));
  $('#s'+n).classList.add('active');
  if(n===2){renderChips();refreshFiles();}
  else{renderDevices(devs.length+1);}
}
function renderChips(){
  const c=$('#chips');c.innerHTML='';
  const names=devs.filter(d=>sel.has(d.sid));
  if(!names.length&&devs.length){
    // all mode
    devs.filter(d=>d.sid!==SID).forEach(addChip);
  }else names.forEach(addChip);
  function addChip(d){
    const el=document.createElement('span');
    el.className='chip';el.innerHTML=`${esc(d.name)} <b onclick="unsel('${d.sid}')">✕</b>`;
    c.appendChild(el);
  }
}
function unsel(sid){
  sel.delete(sid);
  if(!sel.size){go(1);return;}
  renderChips();
}

/* ---------- picking files / folders ---------- */
function pickFiles(files){
  const list=[...files].map(f=>({file:f,rel:f.webkitRelativePath||f.name}));
  sendList(list);
}
const drop=$('#drop');
['dragenter','dragover'].forEach(ev=>drop.addEventListener(ev,e=>{
  e.preventDefault();drop.classList.add('over');
}));
['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{
  e.preventDefault();drop.classList.remove('over');
}));
drop.addEventListener('drop',async e=>{
  e.preventDefault();
  const items=[...(e.dataTransfer.items||[])];
  if(!items.length)return;
  const list=[];
  for(const it of items){
    const ent=it.webkitGetAsEntry?it.webkitGetAsEntry():null;
    if(ent)await walk(ent,'',list);
    else{const f=it.getAsFile&&it.getAsFile();if(f)list.push({file:f,rel:f.name});}
  }
  sendList(list);
});
function walk(entry,path,out){
  return new Promise(res=>{
    if(entry.isFile){
      entry.file(f=>{out.push({file:f,rel:path?path+'/'+f.name:f.name});res();},()=>res());
    }else if(entry.isDirectory){
      const rd=entry.createReader(),all=[];
      const readMore=()=>rd.readEntries(async ents=>{
        if(!ents.length){
          for(const e2 of all)await walk(e2,path?path+'/'+entry.name:entry.name,out);
          res();return;
        }
        all.push(...ents);readMore();
      },()=>res());
      readMore();
    }else res();
  });
}

/* ---------- upload (4MB chunks, direct-to-disk) ---------- */
const CH=4*1024*1024;
const CONC=3;
function recipients(){
  const s=devs.filter(d=>sel.has(d.sid)).map(d=>d.sid);
  return s.length?s:'all';
}
async function sendList(list){
  if(!list.length)return;
  goIfNeeded();
  const batch=crypto.randomUUID?crypto.randomUUID():Math.random().toString(36).slice(2);
  let qi=0;
  const worker=async()=>{
    while(qi<list.length){
      const {file,rel}=list[qi++];
      try{await uploadOne(file,rel,batch);}catch(err){
        pushProg(rel,'❌ '+err.message,-1);
      }
    }
  };
  await Promise.all(Array.from({length:Math.min(CONC,list.length)},worker));
  refreshFiles();
}
function goIfNeeded(){
  if(!document.querySelector('#s2.active'))go(2);
}
function uploadOne(file,rel,batch){
  const pid='p'+Math.random().toString(36).slice(2);
  pushProg(rel,file.size,0);
  return (async()=>{
    const r=await fetch('/api/upload/start',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name:file.name,relpath:rel,size:file.size,
        batch,sid:SID,recipients:recipients()})});
    if(!r.ok)throw new Error('start fail '+r.status);
    const {id}=await r.json();
    const t0=performance.now();let sent=0,lastT=t0,lastB=0;
    for(let s=0;s*CH<file.size;s++){
      const blob=file.slice(s*CH,Math.min((s+1)*CH,file.size));
      let tries=0;
      while(true){
        try{
          const rc=await fetch('/api/upload/chunk?id='+id+'&seq='+s,
            {method:'POST',body:blob});
          if(rc.ok)break;
          throw new Error('chunk '+rc.status);
        }catch(err){
          if(++tries>=6)throw err;
          await new Promise(r=>setTimeout(r,250*tries));
        }
      }
      sent+=blob.size;
      const now=performance.now();
      if(now-lastT>400){
        const spd=((sent-lastB)/((now-lastT)/1000))/(1024*1024);
        lastT=now;lastB=sent;
        updateProg(rel,sent,file.size,spd);
      }
    }
    const re=await fetch('/api/upload/end?id='+id,{method:'POST'});
    if(!re.ok)throw new Error('end fail '+re.status);
    const total=(performance.now()-t0)/1000;
    updateProg(rel,file.size,file.size,(file.size/1048576)/Math.max(total,.01),true);
  })();
}
function pushProg(name,size,pct){
  let el=document.getElementById('pr_'+cssid(name));
  if(!el){
    el=document.createElement('div');el.className='tcard';el.id='pr_'+cssid(name);
    el.innerHTML=`<div class="trow"><span class="tname">${esc(name)}</span>
      <span class="tsub st"></span></div><div class="bar"><i></i></div>`;
    $('#prog').prepend(el);
  }
  if(size<0){el.querySelector('.st').textContent='error';el.querySelector('.bar>i').style.background='var(--bad)';return;}
  el.querySelector('.bar>i').style.width='0%';
}
function updateProg(name,sent,size,spd,done){
  const el=document.getElementById('pr_'+cssid(name));if(!el)return;
  const pct=size?Math.round(sent/size*100):100;
  el.querySelector('.bar>i').style.width=pct+'%';
  el.querySelector('.st').textContent=done?'✅ done · '+spd.toFixed(1)+' MB/s'
    :pct+'% · '+spd.toFixed(1)+' MB/s';
}

/* ---------- receiving (auto download + queue) ---------- */
function onIncoming(m){
  toast('📥 '+m.from+' se: '+m.name+' ('+fmtSize(m.size)+')');
  beep();
  dlQueue=dlQueue.then(()=>autoDL(m.id,m.name));
  refreshFiles();
}
function autoDL(id,name){
  return new Promise(res=>{
    const a=document.createElement('a');
    a.href='/api/dl?id='+id;a.download=name;
    document.body.appendChild(a);a.click();a.remove();
    setTimeout(res,900);
  });
}
function beep(){
  try{
    const C=window.AudioContext||window.webkitAudioContext;if(!C)return;
    const ac=new C(),o=ac.createOscillator(),g=ac.createGain();
    o.connect(g);g.connect(ac.destination);o.frequency.value=880;
    g.gain.setValueAtTime(.12,ac.currentTime);
    g.gain.exponentialRampToValueAtTime(.001,ac.currentTime+.35);
    o.start();o.stop(ac.currentTime+.35);
  }catch(e){}
}
/* ---------- received file list ---------- */
async function refreshFiles(){
  const r=await fetch('/api/files');const {files}=await r.json();
  const box=$('#files');box.innerHTML='';
  $('#nofiles').style.display=files.length?'none':'block';
  const batches={};
  files.forEach(f=>{
    (batches[f.batch]=batches[f.batch]||[]).push(f);
  });
  files.forEach(f=>{
    const row=document.createElement('div');row.className='frow';
    row.innerHTML=`<span class="fn">${esc(f.relpath)}</span>
      <span class="fs">${fmtSize(f.size)}</span>
      <span class="ff">from ${esc(f.from)}</span>
      <button class="dl" onclick="dl('${f.id}')">⬇ Download</button>`;
    box.appendChild(row);
  });
  Object.entries(batches).forEach(([b,arr])=>{
    if(arr.length<2)return;
    const row=document.createElement('div');row.className='frow';
    row.innerHTML=`<span class="fn">📁 ${esc(arr[0].relpath.split('/')[0])} <span class="fs">(${arr.length} files)</span></span>
      <button class="dl" onclick="dlzip('${b}')">⬇ Folder (.zip)</button>`;
    box.prepend(row);
  });
}
function dl(id){location.href='/api/dl?id='+id;}
function dlzip(b){location.href='/api/dlzip?batch='+b;}
async function wipe(){
  if(!confirm('Sab received files delete ho jayengi. Pakka?'))return;
  await fetch('/api/wipe',{method:'POST'});refreshFiles();
}

/* ---------- host panel ---------- */
async function loadInfo(){
  const r=await fetch('/api/info');const info=await r.json();
  const drop=$('#ipdrop');drop.innerHTML='';
  info.ips.forEach(x=>{
    const o=document.createElement('option');
    o.value=x.ip;o.textContent=x.ip+' — '+x.label;
    drop.appendChild(o);
  });
  drop.value=info.primary;
  drop.onchange=loadQR;
  if(isHost)$('#hostpanel').classList.add('show');
  $('#btnWipe').style.display=isHost?'':'none';
}
function curIp(){return $('#ipdrop').value;}
async function loadQR(){
  const ip=curIp();
  $('#qr').innerHTML=`<img src="/qr?ip=${encodeURIComponent(ip)}" width="180" height="180">`;
  const r=await fetch('/api/urls');const d=await r.json();
  $('#urltext').textContent=(d.urls.find(u=>u.includes(ip))||d.urls[0]||'')+'  (browser mein bhi yahi khulega)';
}
function copyUrl(){
  navigator.clipboard?.writeText($('#urltext').textContent)
    .then(()=>toast('📋 URL copied'))
    .catch(()=>{
      const ta=document.createElement('textarea');
      ta.value=$('#urltext').textContent;document.body.appendChild(ta);
      ta.select();document.execCommand('copy');ta.remove();toast('📋 copied');
    });
}

/* ---------- utils ---------- */
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function cssid(s){return [...s].map(c=>c.charCodeAt(0).toString(36)).join('').slice(0,40);}
function fmtSize(b){
  if(b<1024)return b+' B';
  if(b<1048576)return (b/1024).toFixed(1)+' KB';
  if(b<1073741824)return (b/1048576).toFixed(1)+' MB';
  return (b/1073741824).toFixed(2)+' GB';
}
function fmtDur(s){
  if(s<60)return s+'s';
  if(s<3600)return Math.floor(s/60)+'m';
  return Math.floor(s/3600)+'h';
}
function toast(msg){
  const t=document.createElement('div');t.className='toast';t.textContent=msg;
  $('#toasts').appendChild(t);
  setTimeout(()=>{t.style.opacity='0';t.style.transition='.4s';setTimeout(()=>t.remove(),400);},3500);
}
window.addEventListener('beforeunload',()=>ws&&ws.close());

/* ---------- boot ---------- */
loadInfo().then(loadQR);
if(isHost)$('#hostpanel').classList.add('show');
renderDevices(1);
</script>
</body>
</html>
"""


# ------------------------------------------------------------------ main
def main():
    global _PORT, RECV_DIR
    ap = argparse.ArgumentParser(description="LAN Share — offline multi-device transfer")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--dir", default=str(BASE / "Received"))
    ap.add_argument("--fix-firewall", action="store_true",
                    help="Windows firewall allow rule add karo (admin)")
    ap.add_argument("--no-open", action="store_true", help="browser mat kholo")
    a = ap.parse_args()

    _PORT = a.port
    RECV_DIR = Path(a.dir).resolve()
    RECV_DIR.mkdir(parents=True, exist_ok=True)

    primary, ips = lan_ipv4s()
    local_url = f"http://127.0.0.1:{_PORT}/?token={TOKEN}#host"

    print()
    print("  ⚡ LAN Share v" + VERSION + "  (offline, no internet needed)")
    print("  ─────────────────────────────────────────────────────")
    print(f"  Host dashboard : {local_url}")
    print("  Phone links (QR ke andar yehi hote hain):")
    for ip, lbl in ips:
        mark = "  ← default (QR)" if ip == primary else ""
        print(f"    http://{ip}:{_PORT}/?token={TOKEN}   [{lbl}]{mark}")
    print()
    if sys.platform.startswith("win"):
        print("  ⚠ Phone connect nahi ho raha? Admin terminal mein:")
        print(f"      python \"{Path(__file__).name}\" --port {_PORT} --fix-firewall")
        print()
    print("  QR terminal mein neeche hai (phone se scan karo):")
    print()

    try:
        print_qr_terminal(f"http://{primary}:{_PORT}/?token={TOKEN}")
    except Exception as e:
        print(f"  (QR print nahi hua: {e} — upar wala URL use karo)")
        print()

    if a.fix_firewall:
        fix_firewall(_PORT)

    if not a.no_open:
        try:
            import webbrowser
            threading.Timer(0.8, lambda: webbrowser.open(local_url)).start()
        except Exception:
            pass

    try:
        web.run_app(app, host="0.0.0.0", port=_PORT, print=None,
                    handle_signal=True)
    except OSError as e:
        if getattr(e, "errno", None) == 10048 or "10048" in str(e):
            print(f"\n  [X] Port {_PORT} pehle se busy hai.")
            print("      Koi purana LAN Share instance chal raha ho sakta hai.")
            print(f"      Usse band karo ya naya port do:"
                  f"  python lanshare.py --port {_PORT + 1}\n")
        else:
            raise


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  band. (Received/ folder safe hai)")
