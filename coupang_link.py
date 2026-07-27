# -*- coding: utf-8 -*-
"""쿠팡파트너스 Open API — 상품 검색 → 파트너스 링크 생성.

키 위치 (둘 중 하나):
  1) .env 의 COUPANG_ACCESS_KEY / COUPANG_SECRET_KEY
  2) coupang_keys.txt (1줄=Access Key, 2줄=Secret Key) — gitignore됨

검색어 팁(운영 경험 반영): 검색어는 짧게, 결과 여러 개 받아 상품명에
핵심 단어가 든 것을 우선한다.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

BASE_DIR = Path(__file__).parent
KEYS_PATH = BASE_DIR / "coupang_keys.txt"
DOMAIN = "https://api-gateway.coupang.com"
SEARCH_PATH = "/v2/providers/affiliate_open_api/apis/openapi/products/search"


def _keys() -> tuple[str, str] | None:
    from threads_client import _load_env
    _load_env()
    a = os.environ.get("COUPANG_ACCESS_KEY", "").strip()
    s = os.environ.get("COUPANG_SECRET_KEY", "").strip()
    if a and s:
        return a, s
    if KEYS_PATH.exists():
        lines = [x.strip() for x in KEYS_PATH.read_text(encoding="utf-8").splitlines() if x.strip()]
        if len(lines) >= 2:
            return lines[0], lines[1]
    return None


def is_configured() -> bool:
    return _keys() is not None


def _auth_header(method: str, path_with_query: str, access: str, secret: str) -> str:
    dt = datetime.now(timezone.utc).strftime("%y%m%d") + "T" + datetime.now(timezone.utc).strftime("%H%M%S") + "Z"
    path, _, query = path_with_query.partition("?")
    msg = dt + method + path + query
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"CEA algorithm=HmacSHA256, access-key={access}, signed-date={dt}, signature={sig}"


DEEPLINK_PATH = "/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink"


def _shorten(url: str, access: str, secret: str, sub_id: str) -> str | None:
    """긴 상품 URL → 짧은 파트너스 링크 (link.coupang.com/a/XXXX, ~30자).

    스레드는 글자수 500자 제한이라 원본 딥링크(300자+)는 못 쓴다 (실측: 답글 500 에러).
    """
    import requests
    try:
        body = json.dumps({"coupangUrls": [url], "subId": sub_id})
        r = requests.post(
            DOMAIN + DEEPLINK_PATH,
            headers={"Authorization": _auth_header("POST", DEEPLINK_PATH, access, secret),
                     "Content-Type": "application/json"},
            data=body, timeout=15,
        )
        r.raise_for_status()
        data = (r.json().get("data") or [])
        return data[0].get("shortenUrl") if data else None
    except requests.RequestException:
        return None


def search_link(keyword: str, sub_id: str = "threads_kitchen", limit: int = 10) -> dict | None:
    """검색어로 상품을 찾아 {name, price, url(단축)} 반환. 실패/미설정 시 None."""
    creds = _keys()
    if not creds:
        return None
    import requests
    access, secret = creds
    path = f"{SEARCH_PATH}?keyword={quote(keyword)}&limit={limit}&subId={quote(sub_id)}"
    try:
        r = requests.get(
            DOMAIN + path,
            headers={"Authorization": _auth_header("GET", path, access, secret)},
            timeout=15,
        )
        r.raise_for_status()
        items = (r.json().get("data") or {}).get("productData") or []
        if not items:
            return None
        # 핵심 단어 포함 우선 정렬 (운영 경험: 긴 검색어는 엉뚱한 1위가 나옴)
        words = keyword.split()
        items.sort(key=lambda p: -sum(w in p.get("productName", "") for w in words))
        top = items[0]
        url = top.get("productUrl")
        # 단축 API는 원상품 URL만 받는다 — 제휴 링크에서 상품 번호를 뽑아 재구성
        short = None
        if url:
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(url).query)
            page_key = (q.get("pageKey") or [None])[0]
            item_id = (q.get("itemId") or [None])[0]
            if page_key:
                raw = f"https://www.coupang.com/vp/products/{page_key}"
                if item_id:
                    raw += f"?itemId={item_id}"
                short = _shorten(raw, access, secret, sub_id)
        return {
            "name": top.get("productName", keyword),
            "price": top.get("productPrice"),
            "url": short or url,
        }
    except requests.RequestException:
        return None
