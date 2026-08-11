# -*- coding: utf-8 -*-
"""One-time WordPress.com OAuth code exchange.

Reads a JSON object from stdin and writes only the resulting access token and
site URL to the git-ignored .env file. Secrets and tokens are never printed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

BASE = Path(__file__).parent
ENV_PATH = BASE / ".env"


def update_env(values: dict[str, str]):
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    keys = set(values)
    kept = [line for line in lines if not ("=" in line and line.split("=", 1)[0].strip() in keys)]
    kept.extend(f"{key}={value}" for key, value in values.items())
    ENV_PATH.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    payload = json.loads(sys.stdin.readline())
    response = requests.post(
        "https://public-api.wordpress.com/oauth2/token",
        data={
            "client_id": payload["client_id"],
            "client_secret": payload["client_secret"],
            "redirect_uri": payload["redirect_uri"],
            "grant_type": "authorization_code",
            "code": payload["code"],
        },
        timeout=30,
    )
    if not response.ok:
        print(f"WordPress token exchange failed ({response.status_code})", file=sys.stderr)
        return 1
    token = str(response.json().get("access_token") or "").strip()
    if not token:
        print("WordPress token response had no access token", file=sys.stderr)
        return 1
    update_env({
        "WORDPRESS_SITE": payload["site"],
        "WORDPRESS_ACCESS_TOKEN": token,
    })
    print("WordPress access token saved securely to .env")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
