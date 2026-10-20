"""lanshare integration test: auth, QR, WS devices, chunked upload,
multi-device broadcast, download roundtrip, folder zip."""
import asyncio, hashlib, io, json, sys, zipfile
import aiohttp

BASE = "http://127.0.0.1:8765"
TOKEN = sys.argv[1]
H = {"X-LS-Token": TOKEN}
ok = fail = 0

def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1; print(f"  PASS  {name}")
    else:
        fail += 1; print(f"  FAIL  {name} {extra}")

async def main():
    async with aiohttp.ClientSession(headers=H) as s:
        # --- auth ---
        async with aiohttp.ClientSession() as s2:
            r = await s2.get(BASE + "/")
            check("no-token page -> 403", r.status == 403)
            r = await s2.get(BASE + "/api/files")
            check("no-token api -> 403", r.status == 403)

        # --- page + cookie ---
        r = await s.get(BASE + f"/?token={TOKEN}")
        body = await r.text()
        check("token page -> 200 + UI", r.status == 200 and "LAN" in body)
        check("cookie set", "lsid" in r.cookies)

        # --- qr + urls ---
        r = await s.get(BASE + "/qr")
        svg = await r.text()
        check("qr svg valid", r.status == 200 and "<svg" in svg)
        r = await s.get(BASE + "/api/urls")
        d = await r.json()
        check("urls contain real ip+token",
              any("192.168" in u and TOKEN in u for u in d["urls"]), str(d))

        # --- ws: sender + recipient register ---
        wsA = await s.ws_connect(BASE + "/ws")
        await wsA.send_json({"ev": "hello", "sid": "devA", "name": "SenderPC", "os": "Windows"})
        m = json.loads((await wsA.receive()).data)
        check("ws welcome", m.get("ev") == "welcome" and m["sid"] == "devA")
        wsB = await s.ws_connect(BASE + "/ws")
        await wsB.send_json({"ev": "hello", "sid": "devB", "name": "PhoneB", "os": "Android"})
        # devA should eventually see devices broadcast with count 3
        m = {"ev": "none"}
        for _ in range(10):
            m = json.loads((await asyncio.wait_for(wsA.receive(), 5)).data)
            if m.get("ev") == "devices" and m["count"] == 3:
                break
        check("device count = 3 (2 clients + host)", m.get("count") == 3, str(m))
        names = {x["name"] for x in m["devices"]}
        check("device names visible", names == {"SenderPC", "PhoneB"}, str(names))

        # --- upload 9MB file from A to B only ---
        import os
        rnd = os.urandom(9 * 1024 * 1024 + 12345)
        sha = hashlib.sha256(rnd).hexdigest()
        r = await s.post(BASE + "/api/upload/start", json={
            "name": "movie.bin", "relpath": "Folder/Sub/movie.bin",
            "size": len(rnd), "batch": "b1", "sid": "devA",
            "recipients": ["devB"]})
        tid = (await r.json())["id"]
        CH = 4 * 1024 * 1024
        for i in range(0, len(rnd), CH):
            rc = await s.post(f"{BASE}/api/upload/chunk?id={tid}&seq={i//CH}",
                              data=rnd[i:i+CH])
            assert rc.status == 200, await rc.text()
        r = await s.post(f"{BASE}/api/upload/end?id={tid}")
        check("upload end ok", r.status == 200)

        # --- B gets incoming broadcast, A gets progress/done ---
        got = None
        for _ in range(15):
            m = json.loads((await asyncio.wait_for(wsB.receive(), 5)).data)
            if m.get("ev") == "incoming":
                got = m; break
        check("recipient got incoming",
              got and got["name"] == "movie.bin" and got["size"] == len(rnd), str(got))
        m = {"ev": "none"}
        for _ in range(20):
            m = json.loads((await asyncio.wait_for(wsA.receive(), 5)).data)
            if m.get("ev") in ("progress", "done"):
                break
        check("sender got ws event", m.get("ev") in ("progress", "done"), str(m))

        # --- download roundtrip ---
        r = await s.get(BASE + f"/api/dl?id={tid}")
        data = await r.read()
        check("download size", len(data) == len(rnd))
        check("download sha256 match", hashlib.sha256(data).hexdigest() == sha)

        # --- second file same batch (folder) ---
        txt = "hello duniya".encode() * 1000
        r = await s.post(BASE + "/api/upload/start", json={
            "name": "notes.txt", "relpath": "Folder/notes.txt",
            "size": len(txt), "batch": "b1", "sid": "devA",
            "recipients": ["devB"]})
        tid2 = (await r.json())["id"]
        await s.post(f"{BASE}/api/upload/chunk?id={tid2}&seq=0", data=txt)
        await s.post(f"{BASE}/api/upload/end?id={tid2}")

        # --- files list ---
        r = await s.get(BASE + "/api/files")
        fl = (await r.json())["files"]
        check("files list has 2", len(fl) == 2)
        check("files from sender name", fl[0]["from"] == "SenderPC")

        # --- folder zip stream ---
        r = await s.get(BASE + "/api/dlzip?batch=b1")
        zbytes = await r.read()
        zf = zipfile.ZipFile(io.BytesIO(zbytes))
        names = zf.namelist()
        check("zip contains both", set(names) == {"Folder/Sub/movie.bin", "Folder/notes.txt"}, str(names))
        check("zip content ok",
              hashlib.sha256(zf.read("Folder/Sub/movie.bin")).hexdigest() == sha
              and zf.read("Folder/notes.txt") == txt)

        # --- wipe ---
        r = await s.post(BASE + "/api/wipe")
        check("wipe ok", r.status == 200)
        r = await s.get(BASE + "/api/files")
        check("files empty after wipe", (await r.json())["files"] == [])
        # after wipe download should 404
        r = await s.get(BASE + f"/api/dl?id={tid}")
        check("dl after wipe -> 404", r.status == 404)

        await wsA.close(); await wsB.close()

    print(f"\n  {ok} passed, {fail} failed")
    sys.exit(1 if fail else 0)

asyncio.run(main())
