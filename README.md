# rvg-box

مدیریت سرور **VLESS** روی هسته‌ی **sing-box** — بدون پنل وب، کنترل کامل از ترمینال.
جایگزین سبک و امن برای پنل‌های پرریسکی مثل RVG (بدون phone-home، بدون آپدیت از سرور شخص ثالث، بدون UI).

## چرا sing-box؟

- هسته‌ی واقعی به زبان Go (C++ نیست، ولی ده‌ها برابر سریع‌تر از relay های پایتونی مثل RVG)
- ترابردهای WS / HTTPUpgrade / gRPC / QUIC با پشتیبانی کامل از اتصالات هم‌زمان
- قابلیت TLS مستقیم (ACME) یا قرارگیری پشت ریورس‌پراکسی
- یک فایل باینری، بدون وابستگی

> ⚠️ توجه: sing-box نسخه‌های جدید (از 1.12 به بعد) ترابرد XHTTP را حذف کرده؛ به‌جایش
> از WS یا HTTPUpgrade استفاده می‌کنیم که همه‌ی کلاینت‌ها (v2rayNG، NekoBox، Streisand، sing-box) پشتیبانی می‌کنند.

## پیش‌نیاز

- پایتون 3 (فقط استاندارد — بدون pip install)
- `sing-box` (روی دبیان: `sudo apt install sing-box`؛ یا از [releases](https://github.com/SagerNet/sing-box/releases))

```bash
sing-box version   # بررسی
```

## شروع سریع

```bash
# ۱) پیکربندی پایه (سرور VPS با دامنه و گواهی TLS)
python3 rvgbox.py init --host vps.example.com --port 443 \
    --tls-cert /etc/letsencrypt/live/vps.example.com/fullchain.pem \
    --tls-key /etc/letsencrypt/live/vps.example.com/privkey.pem

# ۲) کاربر بساز
python3 rvgbox.py user add alice bob
python3 rvgbox.py user add --count 10 user   # user1..user10

# ۳) کانفیگ سرور را رندر و اعتبارسنجی کن
python3 rvgbox.py serve -o server.json
python3 rvgbox.py check

# ۴) اجرا (پورت 443 نیاز به root دارد)
sudo python3 rvgbox.py run
```

لینک هر کاربر:

```bash
python3 rvgbox.py link alice
```

خروجی (در کلاینت‌ها وارد کنید — v2rayNG / NekoBox / Streisand):

```
vless://<uuid>@vps.example.com:443?encryption=none&fp=chrome&type=ws&host=vps.example.com&path=/ws&security=tls&sni=vps.example.com&alpn=http/1.1#rvg-box-alice
```

## دستورها

| دستور | توضیح |
|---|---|
| `init [--host H] [--port P] [--transport ws\|httpupgrade] [--tls-cert F --tls-key F] [--listen IP] [--path P] [--clash-port N]` | ساخت وضعیت پایه (در `~/.config/rvgbox/state.json`) |
| `user add <name...>` | افزودن کاربر (UUID تصادفی) |
| `user add --count N <base>` | افزودن N کاربر با نام پایه (user1..userN) |
| `user list` | فهرست کاربران + لینک |
| `user revoke <name\|uuid>` | حذف کاربر (لینکش بی‌اعتبار می‌شود) |
| `link <name\|uuid>` | لینک vless:// یک کاربر |
| `links` | همه‌ی لینک‌ها |
| `sub [--raw]` | سابسکریپشن base64 (سازگار با v2rayNG) |
| `serve -o server.json` | رندر کانفیگ سرور sing-box |
| `check` | اعتبارسنجی با `sing-box check` |
| `run` | اجرای سرور (پیش‌زمینه) |
| `stats` | اتصالات زنده (Clash API؛ fallback به `ss`) |

## دو حالت استقرار

### ۱) TLS مستقیم (پیشنهادی)

سرور روی پورت 443 با گواهی واقعی (Let's Encrypt):

```bash
sudo apt install certbot
sudo certbot certonly --standalone -d vps.example.com
python3 rvgbox.py init --host vps.example.com --port 443 \
    --tls-cert /etc/letsencrypt/live/vps.example.com/fullchain.pem \
    --tls-key /etc/letsencrypt/live/vps.example.com/privkey.pem
```

### ۲) پشت ریورس‌پراکسی (بدون گواهی روی sing-box)

sing-box روی پورت بالا بدون TLS گوش می‌دهد؛ Caddy/Nginx گواهی می‌گیرد و پروکسی می‌کند:

```bash
python3 rvgbox.py init --host vps.example.com --port 8443
```

Caddyfile:

```
vps.example.com {
    reverse_proxy 127.0.0.1:8443
}
```

در این حالت لینک‌ها `security=tls` دارند ولی sing-box TLS را نمی‌بیند — TLS در Caddy تمام می‌شود
(دقیقاً همان مدل RVG روی Railway، اما با هسته‌ی واقعی).

### ۳) بدون TLS (فقط تست/شبکه داخلی)

```bash
python3 rvgbox.py init --host 192.168.1.50 --port 4430
# لینک بدون security=tls؛ فقط در شبکه‌ی امن استفاده کنید
```

## امنیت

- **بدون phone-home**: هیچ تماسی با سرور شخص ثالث گرفته نمی‌شود (برخلاف RVG که هر ۵ دقیقه دامنه و هش پسورد را به سرور نویسنده می‌فرستاد)
- **بدون آپدیت خودکار**: کد فقط همان چیزی است که می‌بینید
- UUID هر کاربر کلید دسترسی اوست؛ `user revoke` بلافاصله لینک را بی‌اعتبار می‌کند
- سکرت Clash API تصادفی و فقط روی loopback است
- اگر سرور روی پورت 443 اجرا می‌شود، حتماً `sudo` و فایروال را ببندید: `ufw allow 443/tcp`

## ساختار وضعیت

همه‌چیز در `~/.config/rvgbox/state.json` (JSON ساده — قابل backup و نسخه‌برداری):

```json
{
  "host": "vps.example.com",
  "port": 443,
  "transport": "ws",
  "path": "/ws",
  "tls_cert": "/etc/letsencrypt/.../fullchain.pem",
  "tls_key": "/etc/letsencrypt/.../privkey.pem",
  "clash_secret": "...",
  "clash_port": 9090,
  "users": [{"name": "alice", "uuid": "..."}]
}
```

با متغیر محیطی `RVGBOX_STATE_DIR` می‌توانید چند نمونه‌ی جدا داشته باشید.

## تست

```bash
# بعد از اجرای سرور روی پورت 4430 با کاربر test:
python3 tests/e2e_ws.py <uuid>
# → OK: پاسخ سرور = HTTP/1.1 200 OK
```

تست یک کلاینت مینیمال WebSocket (stdlib) است که هدر VLESS می‌فرستد و از داخل تونل
یک HTTP GET به example.com می‌زند — بدون هیچ وابستگی.
