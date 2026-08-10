#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rvg-box — مدیریت سرور VLESS بر پایه‌ی sing-box، بدون پنل وب.
کنترل کامل از ترمینال: ساخت کانفیگ سرور، مدیریت کاربران (UUID)،
و تولید لینک‌های اشتراک vless:// برای کلاینت‌ها.

وابستگی: فقط binary ی sing-box (sudo apt install sing-box یا دانلود از
https://github.com/SagerNet/sing-box/releases) + پایتون 3 استاندارد.

استفاده:
    rvgbox.py init [--host HOST] [--port PORT] [--transport ws|httpupgrade]
                   [--tls-cert F --tls-key F] [--tls-mode none|direct|edge]
                   [--listen IP] [--path P] [--clash-port N] [--force]
    rvgbox.py user add <name>...            # یک یا چند کاربر
    rvgbox.py user add --count 5 demo       # ۵ کاربر demo1..demo5
    rvgbox.py user list
    rvgbox.py user revoke <name|uuid>
    rvgbox.py link <name|uuid>              # لینک vless:// یک کاربر
    rvgbox.py links                         # همه‌ی لینک‌ها
    rvgbox.py serve [-o server.json]        # رندر کانفیگ سرور (استاندارد: stdout)
    rvgbox.py check                         # اعتبارسنجی با sing-box check
    rvgbox.py run                           # اجرای سرور در پیش‌زمینه
    rvgbox.py stats                         # اتصالات زنده (از Clash API)

مثال کامل:
    rvgbox.py init --host vps.example.com --port 443 \
        --tls-cert /etc/letsencrypt/live/vps.example.com/fullchain.pem \
        --tls-key /etc/letsencrypt/live/vps.example.com/privkey.pem
    rvgbox.py user add alice bob
    rvgbox.py serve -o server.json && rvgbox.py check
    sudo rvgbox.py run          # پورت 443 نیاز به root دارد

استقرار روی Railway (TLS در لبه — بدون گواهی روی sing-box):
    rvgbox.py init --host min-domen.up.railway.app --port 443 --tls-mode edge
    # لینک‌ها security=tls دارند ولی sing-box خودش TLS ندارد — Railway لبه TLS را قطع می‌کند
    # (Dockerfile + railway-entrypoint.sh در ریپو؛ متغیرهای HOST و PORT را Railway می‌دهد)
"""

import argparse
import base64
import json
import os
import secrets
import socket
import subprocess
import sys
import urllib.parse
import uuid as uuidlib
from pathlib import Path

APP_NAME = "rvg-box"
VERSION = "0.1.0"
STATE_DIR = Path(os.environ.get("RVGBOX_STATE_DIR", "~/.config/rvgbox")).expanduser()
STATE_FILE = STATE_DIR / "state.json"
SING_BOX_BIN = os.environ.get("SING_BOX_BIN", "sing-box")

DEFAULT_TRANSPORT = "ws"
DEFAULT_PATH_WS = "/ws"
DEFAULT_PATH_HP = "/hp"          # httpupgrade
CLASH_PORT = 9090
DEFAULT_LISTEN = "0.0.0.0"


# ── State ────────────────────────────────────────────────────────────────────
def load_state() -> dict:
    if not STATE_FILE.exists():
        sys.exit(f"[!] وضعیت پیدا نشد. اول اجرا کنید: {sys.argv[0]} init")
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def find_user(state: dict, key: str) -> dict:
    for u in state["users"]:
        if u["name"] == key or u["uuid"] == key:
            return u
    sys.exit(f"[!] کاربر «{key}» پیدا نشد.")


# ── ساخت لینک vless:// ──────────────────────────────────────────────────────
def vless_link(state: dict, user: dict) -> str:
    host = state["host"]
    port = state["port"]
    transport = state.get("transport", DEFAULT_TRANSPORT)
    tls_mode = state.get("tls_mode",
                         "direct" if (state.get("tls_cert") and state.get("tls_key")) else "none")

    params = {
        "encryption": "none",
        "fp": "chrome",
    }
    if transport == "ws":
        params.update({"type": "ws", "host": host, "path": state.get("path", DEFAULT_PATH_WS)})
    else:  # httpupgrade
        params.update({"type": "httpupgrade", "host": host,
                       "path": state.get("path", DEFAULT_PATH_HP)})
    # edge = TLS در لبه (Railway/CDN/Caddy): کلاینت tls می‌زند ولی sing-box گواهی ندارد
    if tls_mode in ("direct", "edge"):
        params.update({"security": "tls", "sni": host, "alpn": "http/1.1"})

    query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    remark = urllib.parse.quote(f"{APP_NAME}-{user['name']}")
    return f"vless://{user['uuid']}@{host}:{port}?{query}#{remark}"


def sub_content(state: dict) -> str:
    """محتوای سابسکریپشن: همه‌ی لینک‌ها به‌صورت base64 (سازگار با v2rayNG و...)."""
    raw = "\n".join(vless_link(state, u) for u in state["users"])
    return base64.b64encode(raw.encode()).decode()


# ── رندر کانفیگ سرور sing-box ───────────────────────────────────────────────
def render_server(state: dict) -> dict:
    transport_type = state.get("transport", DEFAULT_TRANSPORT)
    path = state.get("path", DEFAULT_PATH_WS if transport_type == "ws" else DEFAULT_PATH_HP)

    inbound = {
        "type": "vless",
        "tag": "vless-in",
        "listen": state.get("listen", DEFAULT_LISTEN),
        # روی Railway پورت با متغیر محیطی PORT داده می‌شود؛ در محلی از state استفاده می‌شود
        "listen_port": int(os.environ.get("PORT") or state["port"]),
        "users": [{"uuid": u["uuid"], "name": u["name"]} for u in state["users"]],
        "transport": {"type": transport_type, "path": path},
    }

    tls_mode = state.get("tls_mode",
                         "direct" if (state.get("tls_cert") and state.get("tls_key")) else "none")
    if tls_mode == "direct":
        inbound["tls"] = {
            "enabled": True,
            "server_name": state["host"],
            "certificate_path": state["tls_cert"],
            "key_path": state["tls_key"],
        }

    config = {
        "log": {"level": "info", "timestamp": True},
        "inbounds": [inbound],
        "outbounds": [
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"},
        ],
        "route": {
            "final": "direct",
            "rules": [{"outbound": "block", "protocol": "dns"}],
        },
        "experimental": {
            "clash_api": {
                "external_controller": f"127.0.0.1:{state.get('clash_port', CLASH_PORT)}",
                "secret": state["clash_secret"],
            }
        },
    }
    return config


# ── دستورها ──────────────────────────────────────────────────────────────────
def cmd_init(args):
    if STATE_FILE.exists() and not args.force:
        state = load_state()
        print(f"[i] وضعیت قبلاً ساخته شده ({STATE_FILE}). (برای بازسازی: --force)")
    else:
        state = {
            "host": args.host,
            "port": args.port,
            "listen": args.listen,
            "transport": args.transport,
            "path": args.path or (DEFAULT_PATH_HP if args.transport == "httpupgrade" else DEFAULT_PATH_WS),
            "tls_cert": args.tls_cert,
            "tls_key": args.tls_key,
            "tls_mode": args.tls_mode or ("direct" if (args.tls_cert and args.tls_key) else "none"),
            "clash_secret": secrets.token_urlsafe(12),
            "clash_port": args.clash_port,
            "users": [],
        }
        save_state(state)
        print(f"[+] وضعیت در {STATE_FILE} ساخته شد.")

    tls_mode = state.get("tls_mode", "direct" if (state.get("tls_cert") and state.get("tls_key")) else "none")
    print(f"    host      : {state['host']}")
    print(f"    port      : {state['port']}  (TLS: {'مستقیم' if tls_mode == 'direct' else ('لبه (edge)' if tls_mode == 'edge' else 'خیر')})")
    print(f"    transport : {state.get('transport')}  path={state.get('path')}")
    print(f"    users     : {len(state['users'])}")
    if not state["users"]:
        print(f"    → اولین کاربر را بسازید: {sys.argv[0]} user add <name>")


def cmd_user(args):
    state = load_state()
    if args.action == "add":
        names = args.names
        if args.count > 1 and len(names) == 1:
            base = names[0]
            names = [f"{base}{i}" for i in range(1, args.count + 1)]
        elif args.count > 1 and len(names) != 1:
            sys.exit("[!] --count فقط با یک نام پایه کار می‌کند (demo → demo1..demoN).")
        for name in names:
            if any(u["name"] == name for u in state["users"]):
                print(f"[!] کاربر «{name}» از قبل وجود دارد؛ رد شد.")
                continue
            state["users"].append({"name": name, "uuid": str(uuidlib.uuid4())})
            print(f"[+] کاربر «{name}» ساخته شد → {state['users'][-1]['uuid']}")
        save_state(state)
    elif args.action == "list":
        if not state["users"]:
            print("[i] هنوز کاربری وجود ندارد.")
        else:
            print(f"{'نام':<16} {'UUID':<38} لینک")
            for u in state["users"]:
                print(f"{u['name']:<16} {u['uuid']:<38} {vless_link(state, u)}")
    elif args.action == "revoke":
        u = find_user(state, args.key)
        state["users"] = [x for x in state["users"] if x["uuid"] != u["uuid"]]
        save_state(state)
        print(f"[-] کاربر «{u['name']}» حذف شد.")


def cmd_link(args):
    state = load_state()
    u = find_user(state, args.key)
    print(vless_link(state, u))


def cmd_links(args):
    state = load_state()
    if not state["users"]:
        sys.exit("[!] کاربری وجود ندارد.")
    for u in state["users"]:
        print(vless_link(state, u))


def cmd_sub(args):
    state = load_state()
    if args.raw:
        print("\n".join(vless_link(state, u) for u in state["users"]))
    else:
        print(sub_content(state))


def cmd_serve(args):
    state = load_state()
    cfg = render_server(state)
    text = json.dumps(cfg, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"[+] کانفیگ سرور در {args.output} نوشته شد. ({len(state['users'])} کاربر)")
    else:
        print(text)


def _run_singbox(args, extra: list[str]) -> int:
    cmd = [SING_BOX_BIN, *extra]
    if args.verbose:
        print(f"[i] اجرا: {' '.join(cmd)}", file=sys.stderr)
    return subprocess.call(cmd)


def cmd_check(args):
    cfg_path = args.config
    if not Path(cfg_path).exists():
        sys.exit(f"[!] فایل {cfg_path} وجود ندارد. اول: {sys.argv[0]} serve -o {cfg_path}")
    rc = _run_singbox(args, ["check", "-c", cfg_path])
    if rc == 0:
        print(f"[+] کانفیگ معتبر است: {cfg_path}")
    sys.exit(rc)


def cmd_run(args):
    cfg_path = args.config
    if not Path(cfg_path).exists():
        sys.exit(f"[!] فایل {cfg_path} وجود ندارد. اول: {sys.argv[0]} serve -o {cfg_path}")
    print(f"[i] اجرای sing-box با {cfg_path} (Ctrl+C برای توقف)")
    sys.exit(_run_singbox(args, ["run", "-c", cfg_path]))


def cmd_stats(args):
    state = load_state()
    port = state.get("clash_port", CLASH_PORT)

    # ۱) تلاش با Clash API (نسخه‌های sing-box که /connections دارند)
    import urllib.request

    secret = state["clash_secret"]
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/connections",
            headers={"Authorization": f"Bearer {secret}"},
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.loads(r.read())
        conns = data.get("connections", [])
        print(f"[Clash API] اتصالات زنده: {len(conns)}")
        total_dl = sum(c.get("download", 0) for c in conns)
        total_ul = sum(c.get("upload", 0) for c in conns)
        print(f"[Clash API] حجم جلسات فعلی — دانلود: {total_dl/1048576:.2f} MB | آپلود: {total_ul/1048576:.2f} MB")
        for c in conns[:20]:
            meta = c.get("metadata", {})
            print(f"  • {meta.get('sourceIP','?')}:{meta.get('sourcePort','?')} → "
                  f"{meta.get('host') or meta.get('destinationIP','?')}:{meta.get('destinationPort','?')}")
        return
    except Exception as e:
        print(f"[i] Clash API ({port}) در دسترس نیست ({e}) — fallback به ss ...")

    # ۲) fallback: اتصالات TCP سطح سیستم روی پورت سرور
    srv_port = state["port"]
    try:
        out = subprocess.run(
            ["ss", "-tn", "state", "established"],
            capture_output=True, text=True, timeout=8,
        ).stdout
    except Exception as e:
        sys.exit(f"[!] ss هم در دسترس نیست: {e}")
    rows = [l.split() for l in out.splitlines() if l.strip()]
    conns = []
    for r in rows[1:]:
        if not r:
            continue
        try:
            local, peer = r[3], r[4]
            l_port = local.rsplit(":", 1)[-1]
            p_port = peer.rsplit(":", 1)[-1]
        except (IndexError, ValueError):
            continue
        if l_port == str(srv_port) or p_port == str(srv_port):
            conns.append((local, peer))
    print(f"[ss] اتصالات زنده روی پورت {srv_port}: {len(conns)}")
    for local, peer in conns[:30]:
        print(f"  • {peer}  ←→  {local}")


def main():
    p = argparse.ArgumentParser(
        prog="rvgbox.py",
        description=f"{APP_NAME} v{VERSION} — مدیریت سرور VLESS با sing-box از ترمینال",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("-v", "--verbose", action="store_true", help="نمایش دستور sing-box در حال اجرا")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="ایجاد وضعیت و پیکربندی پایه")
    pi.add_argument("--host", default=socket.getfqdn() or "localhost", help="دامنه یا IP عمومی سرور")
    pi.add_argument("--port", type=int, default=443, help="پورت شنود (پیش‌فرض 443)")
    pi.add_argument("--listen", default=DEFAULT_LISTEN, help="آدرس شنود (پیش‌فرض 0.0.0.0)")
    pi.add_argument("--transport", choices=["ws", "httpupgrade"], default=DEFAULT_TRANSPORT,
                    help="ترابرد: ws یا httpupgrade (پیش‌فرض ws)")
    pi.add_argument("--path", default=None, help="مسیر ترابرد (پیش‌فرض /ws یا /hp)")
    pi.add_argument("--tls-cert", default=None, help="مسیر گواهی TLS (fullchain.pem) — حالت direct")
    pi.add_argument("--tls-key", default=None, help="مسیر کلید خصوصی TLS (privkey.pem) — حالت direct")
    pi.add_argument("--tls-mode", choices=["none", "direct", "edge"], default=None,
                    help="direct=گواهی روی sing-box | edge=TLS در لبه (Railway/Caddy/CDN) | none=بدون TLS")
    pi.add_argument("--force", action="store_true", help="بازسازی وضعیت حتی اگر موجود باشد (کاربران حذف می‌شوند)")
    pi.add_argument("--clash-port", type=int, default=CLASH_PORT,
                    help="پورت Clash API محلی (پیش‌فرض 9090؛ اگر اشغال بود عوض کنید)")
    pi.set_defaults(func=cmd_init)

    pu = sub.add_parser("user", help="مدیریت کاربران")
    us = pu.add_subparsers(dest="action", required=True)
    ua = us.add_parser("add", help="افزودن کاربر")
    ua.add_argument("names", nargs="+", help="نام یا نام‌های کاربر")
    ua.add_argument("--count", type=int, default=1, help="تعداد (با یک نام پایه: demo → demo1..demoN)")
    ua.set_defaults(func=cmd_user)
    ul = us.add_parser("list", help="فهرست کاربران + لینک")
    ul.set_defaults(func=cmd_user)
    ur_ = us.add_parser("revoke", help="حذف کاربر")
    ur_.add_argument("key", help="نام یا UUID کاربر")
    ur_.set_defaults(func=cmd_user)

    pl = sub.add_parser("link", help="لینک vless:// یک کاربر")
    pl.add_argument("key", help="نام یا UUID کاربر")
    pl.set_defaults(func=cmd_link)

    pls = sub.add_parser("links", help="همه‌ی لینک‌ها")
    pls.set_defaults(func=cmd_links)

    ps = sub.add_parser("sub", help="خروجی سابسکریپشن (base64 برای v2rayNG)")
    ps.add_argument("--raw", action="store_true", help="خروجی متن ساده (بدون base64)")
    ps.set_defaults(func=cmd_sub)

    psv = sub.add_parser("serve", help="رندر کانفیگ سرور sing-box")
    psv.add_argument("-o", "--output", default=None, help="مسیر خروجی (پیش‌فرض: stdout)")
    psv.set_defaults(func=cmd_serve)

    pck = sub.add_parser("check", help="اعتبارسنجی کانفیگ با sing-box check")
    pck.add_argument("--config", default="server.json")
    pck.set_defaults(func=cmd_check)

    pr = sub.add_parser("run", help="اجرای سرور (پیش‌زمینه)")
    pr.add_argument("--config", default="server.json")
    pr.set_defaults(func=cmd_run)

    pst = sub.add_parser("stats", help="اتصالات زنده از Clash API")
    pst.set_defaults(func=cmd_stats)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
