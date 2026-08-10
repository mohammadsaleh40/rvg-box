#!/bin/sh
# rvg-box — بوت غیرتعاملی روی Railway
set -e

# HOST الزامی است: دامنه‌ی عمومی سرویس Railway (از Networking → Generate Domain)
: "${HOST:?متغیر HOST را در Railway تنظیم کنید — دامنه‌ی عمومی سرویس، مثل rvgbox-production.up.railway.app}"
PORT="${PORT:-8080}"          # Railway این پورت را تزریق می‌کند
USER_COUNT="${USER_COUNT:-3}"
USER_PREFIX="${USER_PREFIX:-user}"
STATE_DIR="${RVGBOX_STATE_DIR:-/data}"   # برای ماندگاری UUID ها یک Volume روی /data بزنید
export RVGBOX_STATE_DIR="$STATE_DIR"

echo "==> rvg-box: host=$HOST  port=$PORT  users=${USER_COUNT}  (state=$STATE_DIR)"

# اگر وضعیت قبلی هست (ری‌استارت/Volume)، کاربران حفظ می‌شوند؛ وگرنه تازه ساخته می‌شود
if [ ! -f "$STATE_DIR/state.json" ]; then
    echo "==> ساخت وضعیت تازه (بدون Volume، UUID ها در هر ری‌دیپلوی عوض می‌شوند)"
    python3 rvgbox.py init --host "$HOST" --port 443 --tls-mode edge --force
    python3 rvgbox.py user add --count "$USER_COUNT" "$USER_PREFIX"
else
    echo "==> وضعیت قبلی پیدا شد — کاربران حفظ می‌شوند"
fi

python3 rvgbox.py serve -o server.json
python3 rvgbox.py check --config server.json

echo "==> لینک‌های کاربران (از لاگ Railway بردارید):"
python3 rvgbox.py links

echo "==> اجرای sing-box روی پورت داخلی $PORT"
exec sing-box run -c server.json