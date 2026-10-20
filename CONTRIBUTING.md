# Contributing to LAN Share 🙏

**Welcome!** LAN Share ek chhota, fast, offline file-sharing tool hai —
ise aur behtar banane ke liye contributors ki zaroorat hai. Naye ho to
**"good first issue"** label wali issues se shuru karo. 😊

*New here? Start with issues labeled **good first issue** — they come
with hints and are a friendly first PR.*

---

## Tarike / Ways to contribute

| Kya kar sakte ho | Example |
|---|---|
| 🐛 **Bug report** | "Phone se folder select nahi ho raha" — issue kholo |
| 💡 **Feature idea** | Dark mode, QR style, resume support... |
| 🌍 **Translation** | UI ko Hindi/Urdu/Japanese mein localize karo |
| 📸 **Docs + visuals** | README mein screenshot/GIF add karo |
| 🧑‍💻 **Code** | "good first issue" wali issue uthao → PR bhejo |

---

## Dev setup (2 minute)

```bash
git clone https://github.com/mukund-buddy/lanshare.git
cd lanshare
pip install aiohttp segno          # runtime deps
python lanshare.py --no-open       # server chalu, browser band
```

Tests chalao (server ke bina, ye standalone hain):

```bash
python -m py_compile lanshare.py   # syntax
```

Manual test: `python lanshare.py` → QR scan → phone par bhejo.

---

## Pull request ka process

1. **Pehle issue kholo** (ya existing "good first issue" chuno) — taaki
   duplicate kaam na ho
2. **Fork** karo → branch banao: `git checkout -b fix/my-fix`
3. **Chhota PR** rakho — ek PR = ek change. Bade PR review mein atakte hain
4. **PR description** mein likho: kya badla, kyun, kaise test kiya
5. Review comments ka wait karo — usually 1-3 din mein reply aata hai

### PR checklist

- [ ] `python -m py_compile lanshare.py` clean hai
- [ ] Feature kaam karta hai — phone/PC dono par manually check kiya
- [ ] README zaroorat pade to update kiya
- [ ] Koi personal path/secret commit nahi hua (Received/ ignored hai)

---

## Code style (simple rules)

- **Python**: standard library + aiohttp/segno hi. Naya dependency lana
  ho to pehle issue mein discuss karo
- **JS/UI**: vanilla JS — koi framework nahi (single-file design hai)
- **Comments**: Hinglish chalega 😄 but code English mein
- **Naming**: snake_case (Python), camelCase (JS)
- File badi ho rahi ho (1200+ lines) to refactor PR welcome hai

---

## Har PR ka credit

Har merged contributor README ke **Contributors** section mein dikhega
automatically (GitHub ka contributor graph). Plus release notes mein
mention hoga.

Koi sawaal? Issue mein pooch lo — koi stupid question nahi hota. 🙌
