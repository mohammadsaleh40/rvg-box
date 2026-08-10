#!/usr/bin/env python3
"""تست end-to-end بدون وابستگی: کلاینت مینیمال WebSocket (stdlib فقط) که
یک هدر VLESS می‌فرستد و از داخل تونل یک HTTP GET می‌زند."""
import base64
import os
import socket
import struct
import sys

UUID = sys.argv[1] if len(sys.argv) > 1 else "6b6f689a-8421-4dc6-ae74-faf999cddf52"
TARGET_HOST, TARGET_PORT = "example.com", 80
HOST, PORT, PATH = "127.0.0.1", 4430, "/ws"


def build_vless_header(uuid: str, host: str, port: int) -> bytes:
    ver = bytes([0])
    uid = bytes.fromhex(uuid.replace("-", ""))
    addon = bytes([0])            # addons length = 0
    cmd = bytes([1])              # 1 = TCP connect
    p = struct.pack(">H", port)
    domain = host.encode()
    atype = bytes([2])            # 2 = domain
    addr = bytes([len(domain)]) + domain
    return ver + uid + addon + cmd + p + atype + addr


def ws_connect(sock: socket.socket):
    key = base64.b64encode(os.urandom(16)).decode()
    req = (
        f"GET {PATH} HTTP/1.1\r\n"
        f"Host: {HOST}:{PORT}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(req.encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("اتصال بسته شد")
        resp += chunk
    if b" 101 " not in resp.split(b"\r\n", 1)[0]:
        raise ConnectionError(f"WebSocket handshake ناموفق: {resp[:200]!r}")
    return resp


def ws_send(sock: socket.socket, data: bytes):
    mask = os.urandom(4)
    n = len(data)
    header = b"\x82"  # FIN + binary opcode
    if n < 126:
        header += bytes([0x80 | n])
    elif n < 65536:
        header += bytes([0x80 | 126]) + struct.pack(">H", n)
    else:
        header += bytes([0x80 | 127]) + struct.pack(">Q", n)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    sock.sendall(header + mask + masked)


def ws_recv_frame(sock: socket.socket) -> bytes:
    hdr = _recv_exact(sock, 2)
    opcode = hdr[0] & 0x0F
    ln = hdr[1] & 0x7F
    if ln == 126:
        ln = struct.unpack(">H", _recv_exact(sock, 2))[0]
    elif ln == 127:
        ln = struct.unpack(">Q", _recv_exact(sock, 8))[0]
    payload = _recv_exact(sock, ln)
    if opcode == 0x9:  # ping → pong (ماسک‌شده، چون فریم کلاینت باید ماسک داشته باشد)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        sock.sendall(b"\x8a" + bytes([0x80 | len(payload)]) + mask + masked)
        return b""
    if opcode == 0x8:  # close
        return b""
    return payload


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("اتصال بسته شد")
        buf += chunk
    return buf


def main() -> int:
    payload = (
        b"GET / HTTP/1.1\r\n"
        b"Host: example.com\r\n"
        b"User-Agent: rvgbox-e2e-test\r\n"
        b"Connection: close\r\n\r\n"
    )
    header = build_vless_header(UUID, TARGET_HOST, TARGET_PORT)

    sock = socket.create_connection((HOST, PORT), timeout=10)
    sock.settimeout(10)
    try:
        ws_connect(sock)
        ws_send(sock, header + payload)

        buf = b""
        while True:
            try:
                frame = ws_recv_frame(sock)
            except socket.timeout:
                break
            if not frame:
                break
            buf += frame
            if b"\r\n\r\n" in buf:
                break

        if not buf:
            print("FAIL: پاسخی از تونل نیامد")
            return 1
        if buf.startswith(b"\x00\x00"):  # padding اولیه sing-box
            buf = buf[2:]
        status = buf.split(b"\r\n", 1)[0].decode(errors="replace")
        print(f"OK: پاسخ سرور = {status}")
        print(f"OK: {len(buf)} بایت از تونل دریافت شد")
        return 0
    finally:
        sock.close()


sys.exit(main())
