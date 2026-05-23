#!/usr/bin/env python3
"""Generate a VAPID key pair for Web Push.

Usage:
    python3 scripts/generate-vapid-keys.py

Prints lines suitable for pasting into .env:
    VAPID_PUBLIC_KEY=...
    VAPID_PRIVATE_KEY=...

The public key is also base64-url encoded (raw) for the browser
PushManager.subscribe({applicationServerKey: ...}) call. py-vapid emits
the private key as PEM and the public key as uncompressed point bytes;
we re-encode to base64url as the spec demands.
"""
from __future__ import annotations

import base64
import sys


def main() -> int:
    try:
        from py_vapid import Vapid
    except ImportError:
        print("py-vapid is not installed. Install with: pip install pywebpush", file=sys.stderr)
        return 1

    v = Vapid()
    v.generate_keys()

    private_pem = v.private_pem().decode("utf-8")
    public_raw = v.public_key.public_bytes(
        encoding=__import__("cryptography").hazmat.primitives.serialization.Encoding.X962,
        format=__import__("cryptography").hazmat.primitives.serialization.PublicFormat.UncompressedPoint,
    )
    public_b64url = base64.urlsafe_b64encode(public_raw).rstrip(b"=").decode("ascii")

    print("# VAPID key pair generated. Paste into .env (and keep VAPID_PRIVATE_KEY secret):")
    print()
    print(f"VAPID_PUBLIC_KEY={public_b64url}")
    print()
    print("VAPID_PRIVATE_KEY<<EOF")
    print(private_pem.strip())
    print("EOF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
