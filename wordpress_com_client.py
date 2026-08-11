# -*- coding: utf-8 -*-
"""WordPress.com REST API client using an OAuth2 bearer token."""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from urllib.parse import quote

import requests

from threads_client import _load_env

PUBLIC_API = "https://public-api.wordpress.com"


def credentials() -> tuple[str, str] | None:
    _load_env()
    site = os.environ.get("WORDPRESS_SITE", "").strip(" \t\r\n\ufeff\u200b")
    token = os.environ.get("WORDPRESS_ACCESS_TOKEN", "").strip(" \t\r\n\ufeff\u200b")
    if "://" in site:
        site = site.split("://", 1)[1].strip("/")
    return (site, token) if site and token else None


def is_configured() -> bool:
    return credentials() is not None


class WordPressClient:
    def __init__(self, site: str, access_token: str,
                 session: requests.Session | None = None):
        self.site = site
        self.api = f"{PUBLIC_API}/wp/v2/sites/{quote(site, safe='')}"
        self.http = session or requests.Session()
        self.http.headers.update({
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "recipe-publisher/2.0",
        })

    @classmethod
    def from_env(cls) -> "WordPressClient":
        creds = credentials()
        if not creds:
            raise RuntimeError("WordPress.com OAuth 연결값이 없습니다.")
        return cls(*creds)

    @staticmethod
    def _error(response: requests.Response, action: str) -> RuntimeError:
        try:
            data = response.json()
            detail = data.get("message") or data.get("error_description") or data.get("error")
        except Exception:
            detail = response.text
        return RuntimeError(f"WordPress.com {action} 실패 {response.status_code}: {str(detail)[:240]}")

    def verify(self) -> dict:
        response = self.http.get(PUBLIC_API + "/rest/v1.1/me", timeout=30)
        if not response.ok:
            raise self._error(response, "인증 확인")
        return response.json()

    def find_post(self, slug: str) -> dict | None:
        response = self.http.get(
            self.api + "/posts",
            params={"slug": slug, "status": "any", "context": "edit", "per_page": 1},
            timeout=30,
        )
        if not response.ok:
            raise self._error(response, "중복 확인")
        posts = response.json()
        return posts[0] if posts else None

    def upload_media(self, path: Path, alt_text: str = "") -> dict:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        response = self.http.post(
            self.api + "/media",
            headers={
                "Content-Type": mime,
                "Content-Disposition": f'attachment; filename="{path.name}"',
            },
            data=path.read_bytes(), timeout=120,
        )
        if not response.ok:
            raise self._error(response, f"이미지 업로드({path.name})")
        media = response.json()
        if alt_text:
            update = self.http.post(
                self.api + f"/media/{media['id']}", json={"alt_text": alt_text}, timeout=30
            )
            if update.ok:
                media = update.json()
        return media

    def publish(self, *, title: str, content: str, slug: str,
                featured_media: int | None = None, excerpt: str = "") -> dict:
        existing = self.find_post(slug)
        if existing:
            existing["_already_exists"] = True
            return existing
        payload: dict = {
            "title": title,
            "content": content,
            "slug": slug,
            "status": "publish",
            "comment_status": "closed",
        }
        if featured_media:
            payload["featured_media"] = featured_media
        if excerpt:
            payload["excerpt"] = excerpt
        response = self.http.post(self.api + "/posts", json=payload, timeout=60)
        if not response.ok:
            raise self._error(response, "글 발행")
        return response.json()
