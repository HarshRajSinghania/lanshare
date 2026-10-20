"""QR printer verification:
1) print_qr_terminal output ko wapas matrix mein parse karke segno se compare
2) matrix se image bana kar OpenCV se optical decode (jaise phone scan karega)
"""
import io, sys
from contextlib import redirect_stdout

import numpy as np
import cv2
import segno
from lanshare import print_qr_terminal

URL = "http://192.168.1.3:8765/?token=TESTTOKEN_abc-123_xyz"
ok = fail = 0

def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1; print(f"  PASS  {name}")
    else:
        fail += 1; print(f"  FAIL  {name} {extra}")

# --- capture printed QR ---
buf = io.StringIO()
with redirect_stdout(buf):
    print_qr_terminal(URL)
lines = [ln.rstrip() for ln in buf.getvalue().splitlines()]
check("printed lines exist", len(lines) > 10, f"({len(lines)})")
check("width fits 80-col console", all(len(l) <= 60 for l in lines),
      f"(max {max(len(l) for l in lines)})")
check("no ANSI escape codes", "\x1b" not in buf.getvalue())

# --- parse half-blocks back to matrix ---
parsed = []
for ln in lines:
    top, bot = [], []
    for ch in ln:
        top.append(ch in ("█", "▀"))
        bot.append(ch in ("█", "▄"))
    parsed.append(top)
    parsed.append(bot)
# rstrip se rows ragged ho sakte hain — equal width mein pad karo
_W = max(len(r) for r in parsed)
parsed = [r + [False] * (_W - len(r)) for r in parsed]

qr = segno.make(URL, error="m")
m = [list(r) for r in qr.matrix]
pad = 2
padded = [[False] * (len(m[0]) + pad * 2) for _ in range(pad)]
for row in m:
    padded.append([False] * pad + row + [False] * pad)
padded += [[False] * (len(m[0]) + pad * 2) for _ in range(pad)]

# content bounding box nikal kar segno matrix se exact compare
def content_box(mat):
    ys = [y for y, r in enumerate(mat) if any(r)]
    xs = [x for r in mat for x, v in enumerate(r) if v]
    y0, y1, x0, x1 = min(ys), max(ys), min(xs), max(xs)
    return [r[x0:x1 + 1] for r in mat[y0:y1 + 1]]

p_box = content_box(parsed)
m_box = [list(r) for r in qr.matrix]
check("content dims match segno matrix",
      len(p_box) == len(m_box) and len(p_box[0]) == len(m_box[0]),
      f"({len(p_box)}x{len(p_box[0])} vs {len(m_box)}x{len(m_box[0])})")
same = p_box == m_box
check("terminal QR == segno matrix (pixel-exact)", same)

# --- optical decode via OpenCV — MERE terminal output se (phone jaisa scan) ---
S = 8    # module -> pixels
M = 4    # quiet zone (modules) — scanner ke liye zaroori
H = (len(p_box) + 2 * M) * S
Wd = (len(p_box[0]) + 2 * M) * S
img = np.ones((H, Wd), dtype=np.uint8) * 255
for y, row in enumerate(p_box):
    for x, v in enumerate(row):
        if v:
            img[(y+M)*S:(y+M+1)*S, (x+M)*S:(x+M+1)*S] = 0
data, pts, _ = cv2.QRCodeDetector().detectAndDecode(img)
check("OpenCV decode == exact URL", data == URL, f"(got: {data!r})")

print(f"\n  {ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
