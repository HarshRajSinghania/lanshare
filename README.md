# ⚡ LAN Share

**Offline multi-device file/folder transfer — no internet needed.**
One device runs the server, everyone else just **scans a QR code** and the
file manager opens in their browser. No app install. Ever.

> **Quick start:** install [Python](https://www.python.org/downloads/)
> (tick *"Add Python to PATH"*), then **double-click `lanshare.bat`**. Done.
> A QR code appears on screen — scan it from any phone.

---

## Features

| | |
|---|---|
| 📱 **Real QR codes** | Scanning opens the actual app URL in the phone's browser — not a dummy image |
| ♾️ **Unlimited devices** | Laptops, phones, TVs — connect as many as you want, not just 2 |
| 🎯 **Staged UI** | See *"N devices connected"* first → pick device(s) → only then the file-sharing options appear |
| 📡 **Send to 1–3 devices at once** | Check any number of devices and send to all of them simultaneously |
| 📤 **"Send to all devices"** | One button broadcasts files *and* folders to everyone on the connection |
| 📱⇄📱 **Phone to phone** | Any Android phone can be the host via [Termux](https://termux.dev) — no PC needed |
| 🚀 **Fast & unlimited size** | 4 MB streamed chunks written straight to disk — measured **~40 MB/s up / ~150 MB/s down** on loopback; a 4 GB movie never touches RAM twice |
| 🧹 **Zero-history session** | Random session token, nothing stored in the browser, one-click **Wipe Session** button |
| 📁 **Folders with structure** | Sub-folder paths preserved; any folder can be downloaded as a streamed `.zip` |

---

## Usage

**Host device (the one running `lanshare.bat` / `lanshare.py`):**
- A QR code + all local URLs are printed in the terminal, and the host
  dashboard opens in your browser automatically.
- As phones scan, the live device count grows.
- **Wipe Session** deletes everything in `Received/` instantly.

**Phones / other devices (after scanning):**
1. **Screen 1** — *"N devices connected"* + device list. Tap devices to
   select them, or hit **"Send to all devices"**.
2. **Screen 2** — pick **Files**, **Folder** or **Multiple Folders**, or
   just **drag & drop**. Up to 3 files upload in parallel with live
   progress and MB/s.
3. On the receiving side files **auto-download** with a beep + toast.
   For folders, the receiver also gets a **"📁 Folder (.zip)"** button.

### Options

```
python lanshare.py --port 8765        # custom port
python lanshare.py --dir D:\Shares    # where received files go
python lanshare.py --fix-firewall     # Windows firewall rule (run as admin)
python lanshare.py --no-open          # don't auto-open the browser
```

### Phone ⇄ Phone (no PC at all)

Run the host on an Android phone with [Termux](https://termux.dev):

```bash
pkg install python
pip install aiohttp segno
python lanshare.py
```

Any other phone scans that QR — done.

### Windows firewall not letting phones connect?

Right-click `lanshare.bat` → **Run as administrator**, or:

```
python lanshare.py --fix-firewall
```

### About "open in incognito"

No QR code or URL can force a browser into incognito mode — that is a
browser restriction, not something an app can override. So LAN Share is
built **zero-history** instead: session-only random token, nothing saved
in the browser, no logs. If you still want incognito: scan → browser
menu → **New Incognito Tab** → paste the URL.

---

## Tests

```bash
python test_lanshare.py <token>   # 21 integration checks
python perf_test.py <token>       # speed measurement (200 MB)
```

The token is printed in the server terminal on startup.

---

---

# 🇮🇳 हिंग्लिश वर्ज़न (Hinglish)

**Ye ek offline file-sharing tool hai — internet ki bilkul zaroorat nahi.**
Ek device host banta hai (server chalta hai), baaki sab QR scan karke
browser mein khud connect ho jaate hain. Koi app install nahi. Koi data
kharch nahi.

> **Sabse pehle:** [Python](https://www.python.org/downloads/) install
> karo (installer mein *"Add Python to PATH"* **tick zaroor karna**), phir
> **`lanshare.bat` par double-click**. Bas. Screen par QR aayega — phone
> se scan karo, browser mein tool khul jayega.

---

## Features

| | |
|---|---|
| 📱 **Asli QR code** | Scan karte hi phone ka browser **uska URL kholta hai** — dummy QR nahi |
| ♾️ **Unlimited devices** | 2 nahi, jitne chaaho utne — laptop, phone, TV, sab |
| 🎯 **Step-by-step UI** | Pehle *"kitne devices connected"* dikhta hai → device chuno → phir file-sharing options aate hain (sab kuch ek saath nahi) |
| 📡 **1–3 devices ek saath** | Jitne chaho devices tick karo aur sabko ek saath bhejo |
| 📤 **"Sabhi devices pe bhejo"** | Ek button — files aur folders dono sabke paas chale jaate hain |
| 📱⇄📱 **Phone ⇄ Phone** | Ek Android phone [Termux](https://termux.dev) se host ban sakta hai — PC ki zaroorat hi nahi |
| 🚀 **Fast, unlimited size** | 4 MB chunks, seedha disk mein write — measured **~40 MB/s up / ~150 MB/s down** (local). 4 GB ki movie bhi RAM nahi jalati |
| 🧹 **Zero-history** | Random session token, browser mein kuch save nahi, ek click mein **Wipe Session** |
| 📁 **Folders poore structure ke saath** | Sub-folders ke paths safe rehte hain; koi bhi folder `.zip` mein download ho sakta hai |

---

## Use kaise karna

**Host device (jisne `lanshare.bat` / `lanshare.py` chalaya):**
- Terminal mein QR + saare LAN URLs print hote hain
- Apna browser mein **host dashboard** khud khul jata hai
- Phone scan karte hi live count badhta hai
- **Wipe Session** button sab received files turant delete karta hai

**Phone / baaki devices (QR scan karne ke baad):**
1. **Screen 1** — *"N devices connected"* + device list. Device tick karo
   (1-3 ya jitne chaho) ya **"Sabhi devices pe bhejo"** dabao
2. **Screen 2** — **Files** / **Folder** / **Multiple Folders** buttons ya
   **drag & drop**. 3 files ek saath parallel jaati hain — live progress
   + MB/s dikhta hai
3. Samne wale device par file **auto-download** + beep + toast aati hai.
   Folder bhejne par neeche **"📁 Folder (.zip)"** ka button bhi aata hai

### Options

```
python lanshare.py --port 8765        # port badlo
python lanshare.py --dir D:\Shares    # files kahan rakhni hain
python lanshare.py --fix-firewall     # Windows firewall allow (admin se)
python lanshare.py --no-open          # browser mat kholo
```

### Phone ⇄ Phone (bina PC ke)

Ek Android phone par [Termux](https://termux.dev) mein:

```bash
pkg install python
pip install aiohttp segno
python lanshare.py
```

Doosra phone uska QR scan kare — bas ho gaya.

### Phone connect nahi ho raha? (Windows firewall)

`lanshare.bat` par **right-click → Run as administrator**, ya:

```
python lanshare.py --fix-firewall
```

Ya manually: Windows Security → Firewall → Python ko Private + Public
network par allow kar do.

### Incognito ke baare mein (poora sach)

Koi bhi QR ya URL browser ko **force incognito mein khulne ka permission
nahi de sakta** — ye browser ki restriction hai, koi tool isse bypass
nahi kar sakta. Isliye LAN Share ko **zero-history** banaya gaya hai:
session-only random token, browser mein kuch save nahi, server par koi
log nahi. Phir bhi incognito chahiye to: scan karo → browser menu →
**New Incognito Tab** → URL paste karo. Bas.

## Tests

```
python test_lanshare.py <token>   # 21 integration checks
python perf_test.py <token>       # speed check (200 MB)
```

Token server ke terminal mein startup par print hota hai.
