"""Quick throughput measurement: 200MB chunked upload + download."""
import asyncio, os, sys, time
import aiohttp

BASE = "http://127.0.0.1:8765"
TOKEN = sys.argv[1]
H = {"X-LS-Token": TOKEN}
SIZE = 200 * 1024 * 1024
CH = 4 * 1024 * 1024

async def main():
    rnd = os.urandom(8 * 1024 * 1024) * (SIZE // (8 * 1024 * 1024))  # fast gen
    async with aiohttp.ClientSession(headers=H) as s:
        r = await s.post(BASE + "/api/upload/start", json={
            "name": "perf.bin", "relpath": "perf.bin", "size": len(rnd),
            "batch": "perf", "sid": "perf", "recipients": "all"})
        tid = (await r.json())["id"]
        t0 = time.perf_counter()
        for i in range(0, len(rnd), CH):
            rc = await s.post(f"{BASE}/api/upload/chunk?id={tid}&seq={i//CH}",
                              data=rnd[i:i+CH])
            assert rc.status == 200
        await s.post(f"{BASE}/api/upload/end?id={tid}")
        up = time.perf_counter() - t0
        print(f"  upload   : {SIZE/1048576:.0f} MB in {up:.2f}s = "
              f"{SIZE/1048576/up:.1f} MB/s")

        t0 = time.perf_counter()
        got = 0
        async with s.get(BASE + f"/api/dl?id={tid}") as resp:
            async for chunk in resp.content.iter_chunked(1 << 20):
                got += len(chunk)
        dn = time.perf_counter() - t0
        assert got == len(rnd)
        print(f"  download : {got/1048576:.0f} MB in {dn:.2f}s = "
              f"{got/1048576/dn:.1f} MB/s")

        # zip path (200MB single file stored)
        t0 = time.perf_counter()
        z = 0
        async with s.get(BASE + "/api/dlzip?batch=perf") as resp:
            async for chunk in resp.content.iter_chunked(1 << 20):
                z += len(chunk)
        zt = time.perf_counter() - t0
        print(f"  zip dl   : {z/1048576:.0f} MB in {zt:.2f}s = "
              f"{z/1048576/zt:.1f} MB/s")

        await s.post(BASE + "/api/wipe")

asyncio.run(main())
