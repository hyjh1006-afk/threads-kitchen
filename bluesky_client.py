# -*- coding: utf-8 -*-
"""Small Bluesky AT Protocol client for an optional recipe teaser post."""
from __future__ import annotations

import io
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image

from threads_client import _load_env

DEFAULT_SERVICE = "https://bsky.social"


def public_url(uri: str, handle: str) -> str:
    return f"https://bsky.app/profile/{handle}/post/{uri.rsplit('/', 1)[-1]}"


def credentials() -> tuple[str, str] | None:
    _load_env()
    handle = os.environ.get("BLUESKY_HANDLE", "").strip(" \t\r\n\ufeff\u200b")
    password = os.environ.get("BLUESKY_APP_PASSWORD", "").strip(" \t\r\n\ufeff\u200b")
    return (handle, password) if handle and password else None


def is_configured() -> bool:
    return credentials() is not None


def _image_bytes(path: Path, max_bytes: int = 950_000) -> tuple[bytes, str]:
    """Fit an image under Bluesky's blob limit without modifying the source."""
    with Image.open(path) as source:
        image = source.convert("RGB")
        image.thumbnail((1800, 1800))
        for quality in (88, 80, 72, 64, 55):
            out = io.BytesIO()
            image.save(out, "JPEG", quality=quality, optimize=True)
            if out.tell() <= max_bytes:
                return out.getvalue(), "image/jpeg"
        out = io.BytesIO()
        image.thumbnail((1200, 1200))
        image.save(out, "JPEG", quality=50, optimize=True)
        return out.getvalue(), "image/jpeg"


def _link_facet(text: str, url: str) -> list[dict]:
    if not url:
        return []
    start = text.find(url)
    if start < 0:
        return []
    byte_start = len(text[:start].encode("utf-8"))
    byte_end = byte_start + len(url.encode("utf-8"))
    return [{
        "index": {"byteStart": byte_start, "byteEnd": byte_end},
        "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
    }]


class BlueskyClient:
    def __init__(self, handle: str, app_password: str,
                 session: requests.Session | None = None):
        self.handle = handle
        self.app_password = app_password
        self.http = session or requests.Session()
        self.service = DEFAULT_SERVICE
        self.did = ""
        self.token = ""

    @classmethod
    def from_env(cls) -> "BlueskyClient":
        creds = credentials()
        if not creds:
            raise RuntimeError("Bluesky 연결값이 없습니다.")
        return cls(*creds)

    def _xrpc(self, method: str, name: str, **kwargs) -> requests.Response:
        return self.http.request(method, f"{self.service}/xrpc/{name}", timeout=60, **kwargs)

    def login(self) -> dict:
        response = self._xrpc(
            "POST", "com.atproto.server.createSession",
            json={"identifier": self.handle, "password": self.app_password},
        )
        if not response.ok:
            raise RuntimeError(f"Bluesky 로그인 실패 {response.status_code}: {response.text[:200]}")
        data = response.json()
        self.did = data["did"]
        self.token = data["accessJwt"]
        for service in (data.get("didDoc") or {}).get("service") or []:
            endpoint = str(service.get("serviceEndpoint") or "").rstrip("/")
            parsed = urlparse(endpoint)
            if parsed.scheme == "https" and parsed.netloc:
                self.service = endpoint
                break
        self.http.headers.update({"Authorization": f"Bearer {self.token}"})
        return data

    def upload_image(self, path: Path) -> dict:
        blob, mime = _image_bytes(path)
        response = self._xrpc(
            "POST", "com.atproto.repo.uploadBlob",
            headers={"Content-Type": mime}, data=blob,
        )
        if not response.ok:
            raise RuntimeError(f"Bluesky 이미지 업로드 실패 {response.status_code}: {response.text[:200]}")
        return response.json()["blob"]

    def post(self, text: str, *, link: str = "", images: list[Path] | None = None,
             alt_text: str = "", reply_root: dict | None = None,
             reply_parent: dict | None = None) -> dict:
        if not self.token:
            self.login()
        if len(text) > 300:
            raise ValueError("Bluesky 글은 300자를 넘을 수 없습니다.")
        record: dict = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        facets = _link_facet(text, link)
        if facets:
            record["facets"] = facets
        if reply_root and reply_parent:
            record["reply"] = {
                "root": {"uri": reply_root["uri"], "cid": reply_root["cid"]},
                "parent": {"uri": reply_parent["uri"], "cid": reply_parent["cid"]},
            }
        if images:
            embedded = [
                {"alt": alt_text[:1000], "image": self.upload_image(path)}
                for path in images[:4]
            ]
            if embedded:
                record["embed"] = {"$type": "app.bsky.embed.images", "images": embedded}
        response = self._xrpc(
            "POST", "com.atproto.repo.createRecord",
            json={"repo": self.did, "collection": "app.bsky.feed.post", "record": record},
        )
        if not response.ok:
            raise RuntimeError(f"Bluesky 게시 실패 {response.status_code}: {response.text[:200]}")
        return response.json()

    def delete_post(self, uri: str) -> None:
        if not self.token:
            self.login()
        response = self._xrpc(
            "POST", "com.atproto.repo.deleteRecord",
            json={
                "repo": self.did,
                "collection": "app.bsky.feed.post",
                "rkey": uri.rsplit("/", 1)[-1],
            },
        )
        if not response.ok:
            raise RuntimeError(f"Bluesky delete failed {response.status_code}: {response.text[:200]}")

    def get_post(self, uri: str) -> dict:
        """Return the current strong reference for an AT URI."""
        if not self.token:
            self.login()
        parts = uri.split("/")
        if len(parts) < 5 or not uri.startswith("at://"):
            raise ValueError(f"Invalid AT URI: {uri}")
        response = self._xrpc(
            "GET", "com.atproto.repo.getRecord",
            params={"repo": parts[2], "collection": parts[3], "rkey": parts[4]},
        )
        if not response.ok:
            raise RuntimeError(f"Bluesky post read failed {response.status_code}: {response.text[:200]}")
        data = response.json()
        return {"uri": data["uri"], "cid": data["cid"]}

    def post_thread(self, texts: list[str], *, images: list[Path] | None = None,
                    alt_text: str = "", links: list[str] | None = None) -> dict:
        if len(texts) != 3:
            raise ValueError("A recipe thread must contain exactly three posts.")
        links = links or ["", "", ""]
        if len(links) != 3:
            raise ValueError("links must contain exactly three entries.")
        created: list[dict] = []
        try:
            root = self.post(texts[0], link=links[0], images=images, alt_text=alt_text)
            created.append(root)
            first_reply = self.post(
                texts[1], link=links[1], reply_root=root, reply_parent=root,
            )
            created.append(first_reply)
            second_reply = self.post(
                texts[2], link=links[2], reply_root=root, reply_parent=first_reply,
            )
            created.append(second_reply)
            return {"root": root, "replies": [first_reply, second_reply]}
        except Exception:
            for post in reversed(created):
                try:
                    self.delete_post(post["uri"])
                except Exception:
                    pass
            raise

    def update_profile(self, *, display_name: str, description: str) -> dict:
        if not self.token:
            self.login()
        current = self._xrpc(
            "GET", "com.atproto.repo.getRecord",
            params={
                "repo": self.did,
                "collection": "app.bsky.actor.profile",
                "rkey": "self",
            },
        )
        if not current.ok:
            raise RuntimeError(f"Bluesky profile read failed {current.status_code}: {current.text[:200]}")
        record = current.json()["value"]
        record["displayName"] = display_name
        record["description"] = description
        response = self._xrpc(
            "POST", "com.atproto.repo.putRecord",
            json={
                "repo": self.did,
                "collection": "app.bsky.actor.profile",
                "rkey": "self",
                "record": record,
            },
        )
        if not response.ok:
            raise RuntimeError(f"Bluesky profile update failed {response.status_code}: {response.text[:200]}")
        return response.json()
