# استقرار روی Railway

این راهنما فرض می‌کند ریپو را روی گیت‌هاب خودت دارید (مثلاً `mohammadsaleh40/rvg-box`).

## معماری

```
کلاینت (vless:// + ws + security=tls)
   │  پورت 443، دامنه‌ی *.up.railway.app (TLS خودکار Railway)
   ▼
Railway Edge (TLS را قطع می‌کند → ws خام)
   ▼
کانتینر: sing-box (VLESS+ws) روی پورت داخلی $PORT (مثلاً 8080)
```

- **TLS در لبه‌ی Railway است**، نه روی sing-box → حالت `--tls-mode edge`
- لینک کاربران `security=tls&sni=<دامنه>` دارد ولی sing-box خودش گواهی ندارد
- Railway همه‌ی مسیرها (path) را به کانتینر می‌فرستد → هر path ای کار می‌کند (پیش‌فرض `/ws`)

## مراحل

### ۱) پیش‌نیازها
- اکانت Railway. ⚠️ Railway از ۲۰۲۴ پلن رایگان ندارد: اکانت جدید ۵ دلار اعتبار آزمایشی می‌گیرد و بعد باید کارت بدهی ببندید (~۵ دلار در ماه برای این سرویس).

### ۲) دیپلوی
1. در داشبورد Railway: **New Project → Deploy from GitHub repo** → `mohammadsaleh40/rvg-box` را انتخاب کنید.
2. Railway خودش Dockerfile را تشخیص می‌دهد. بیلد چند دقیقه طول می‌کشد.
3. بعد از اولین دیپلوی، تب **Settings → Networking → Public Networking → Generate Domain** را بزنید تا دامنه بسازد (مثلاً `rvgbox-production.up.railway.app`).
   - Railway از شما **پورت** می‌پرسد: **8080** وارد کنید (پورت داخلی کانتینر = همان `$PORT`؛ در لاگ دیپلوی هم چاپ می‌شود: `port=8080`). این پورت ربطی به پورت کلاینت (443) ندارد — کلاینت همیشه از 443 وصل می‌شود.
   - گزینه‌ی **Generate Domain** (HTTP/HTTPS) را بزنید، نه **TCP Proxy** (برای ws لازم نیست).
4. تب **Variables** این متغیرها را اضافه کنید:
   - `HOST` = دامنه‌ای که ساخته شد (مثلاً `rvgbox-production.up.railway.app`) ← **الزامی**
   - `USER_COUNT` = تعداد کاربر (پیش‌فرض ۳)
   - `USER_PREFIX` = پیشوند نام کاربران (پیش‌فرض `user` → user1, user2, ...)
   - `PORT` را **نزنید** — Railway خودش تزریق می‌کند
5. یک **دیپلوی جدید** بزنید (Deploy → Deployments → Deploy) تا با HOST جدید بالا بیاید.

### ۳) گرفتن لینک‌ها
- تب **Deployments → آخرین دیپلوی → View Logs**
- لینک‌ها زیر «لینک‌های کاربران» چاپ می‌شوند:
  `vless://<uuid>@<دامنه>:443?encryption=none&fp=chrome&type=ws&host=<دامنه>&path=/ws&security=tls&sni=<دامنه>&alpn=http/1.1#rvg-box-user1`
- در v2rayNG / NekoBox / Streisand: از کلیپ‌بورد import کنید.

### ۴) (پیشنهادی) ماندگاری UUID ها
بدون Volume، هر ری‌دیپلوی یک state تازه می‌سازد → UUID ها عوض می‌شوند و لینک‌های قبلی می‌میرند.
برای ماندگاری: **Settings → Volumes → New Volume** با mount path مساوی `/data` (دقیقاً همین مسیر).
از آن پس ری‌استارت و ری‌دیپلوی، کاربران را حفظ می‌کند.

## عیب‌یابی

| مشکل | راه‌حل |
|---|---|
| لاگ: `unknown UUID` | لینک با UUID درست استفاده نشده یا UUID ها بعد از ری‌دیپلوی عوض شده‌اند (Volume بزنید) |
| کلاینت وصل نمی‌شود | بررسی کنید `HOST` دقیقاً دامنه‌ی Railway باشد (بدون https://) و دامنه‌ی تازه در Variable ست شده باشد |
| `init` در لاگ خطا می‌دهد | متغیر `HOST` را ست کنید — entrypoint بدون آن بوت نمی‌شود |
| کانفیگ نامعتبر | لاگ `sing-box check` را ببینید؛ نسخه‌ی pin شده 1.13.18 است (XHTTP ندارد — از ws استفاده می‌کنیم) |

## امنیت

- لینک‌های vless در لاگ‌های Railway دیده می‌شوند — دسترسی به اکانت Railway = دسترسی به UUID ها.
- دامنه‌ی عمومی بودنش خطری نیست: بدون UUID هیچ‌کس نمی‌تواند وصل شود.
- اگر کسی UUID ای لو رفت: `user revoke` (در محلی که state هست) یا در Railway با Volume، `RVGBOX_STATE_DIR` را از `/data` به یک پوشه‌ی تازه عوض کنید تا همه‌ی کاربران نو شوند.

## تست محلی همان‌قدر Docker

```bash
docker build -t rvgbox .
docker run -d --name rvgbox-test \
  -e HOST=test.up.railway.app -e PORT=8080 -e USER_COUNT=2 \
  -p 8443:8080 rvgbox
docker logs rvgbox-test          # UUID ها را بردارید
python3 tests/e2e_ws.py <uuid> 127.0.0.1 8443 /ws
```
