# -*- coding: utf-8 -*-
"""WordPress.com/WordPress REST API client using an Application Password."""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse

import requests

from threads_client import _load_env


def _clean(value: str) -> str:
    return value.strip(" \t\r\n\ufeff\u200b")


def credentials() -> tuple[str, str, str] | None:
    _load_env()
    site = _clean(os.environ.get("WORDPRESS_SITE", ""))
    username = _clean(os.environ.get("WORDPRESS_USERNAME", ""))
    password = _clean(os.environ.get("WORDPRESS_APP_PASSWORD", ""))
    if not (site and username and password):
        return None
    if "://" not in site:
        site = "https://" + site
    parsed = urlparse(site)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("WORDPRESS_SITE는 https 사이트 주소여야 합니다.")
    return site.rstrip("/"), username, password


def is_configured() -> bool:
    return credentials() is not None


class WordPressClient:
    def __init__(self, site: str, username: str, app_password: str,
                 session: requests.Session | None = None):
        self.site = site.rstrip("/")
        self.api = self.site + "/wp-json/wp/v2"
        self.http = session or requests.Session()
        self.http.auth = (username, app_password)
        self.http.headers.update({"User-Agent": "recipe-publisher/1.0"})

    @classmethod
    def from_env(cls) -> "WordPressClient":
        creds = credentials()
        if not creds:
            raise RuntimeError("WordPress 연결값이 없습니다.")
        return cls(*creds)

    @staticmethod
    def _error(response: requests.Response, action: str) -> RuntimeError:
        try:
            detail = response.json().get("message", response.text)
        except Exception:
            detail = response.text
        return RuntimeError(f"WordPress {action} 실패 {response.status_code}: {str(detail)[:240]}")

    def verify(self) -> dict:
        response = self.http.get(self.api + "/users/me", params={"context": "edit"}, timeout=30)
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
        headers = {
            "Content-Type": mime,
            "Content-Disposition": f'attachment; filename="{path.name}"',
        }
        response = self.http.post(
            self.api + "/media", headers=headers, data=path.read_bytes(), timeout=120
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
