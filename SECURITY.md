# Security Policy 🛡️

## Reporting a vulnerability

**Please do NOT open a public issue for security bugs.**

Use GitHub's **private vulnerability reporting**:
Repo → Security tab → "Report a vulnerability"

Maintainer 7 din ke andar reply karega. Critical bugs ke liye credit
diya jayega (agar chaaho to name list mein).

## Threat model (kya safe hai, kya nahi)

LAN Share **local network (LAN)** ke liye banaya gaya hai — internet
ke liye nahi.

| Safe ✅ | Not a goal ❌ |
|---|---|
| Bina token wala koi device connect nahi kar sakta | Hostile Wi-Fi network par encryption (abhi plaintext HTTP) |
| Token random hai, session-only, browser mein save nahi | Internet par expose karna (port forward etc.) |
| Received/ folder git mein kabhi commit nahi hoti | Long-term secret storage |
| Server sirf ek folder se files serve karta hai | Multi-tenant / authentication system |

**Tip:** Public Wi-Fi (cafe, airport) par use mat karo — wahi LAN par
koi file sniff kar sakta hai. Trusted hotspot/home Wi-Fi ke liye best hai.

Known limitation: chunks abhi **bina encryption** ke jaate hain (pure
LAN speed ke liye). Chunk-level encryption ek welcome contribution hai
— #6 issue dekho!
