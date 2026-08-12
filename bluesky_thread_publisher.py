# -*- coding: utf-8 -*-
"""Publish one English recipe as a root post followed by two replies."""
from __future__ import annotations

from pathlib import Path

import bluesky_client
import bluesky_thread_content
import image_gen

BASE = Path(__file__).parent


def local_images(menu: dict, generate: bool = True) -> list[Path]:
    image_dir = BASE / "images"
    paths = sorted(image_dir.glob(f"{menu['id']}_*.png"))
    if not paths:
        legacy = image_dir / f"{menu['id']}.png"
        if legacy.exists():
            paths = [legacy]
    if not paths and generate:
        paths = image_gen.generate_set(menu["image_prompt"], image_dir, menu["id"])
    return paths[:4]


def publish(menu: dict, config: dict, *, generate_images: bool = True) -> dict:
    if not bluesky_client.is_configured():
        raise RuntimeError("Bluesky credentials are not configured.")
    copy = bluesky_thread_content.load_or_generate(menu)
    if not copy:
        raise RuntimeError("A validated English thread could not be generated.")
    paths = local_images(menu, generate=generate_images)
    client = bluesky_client.BlueskyClient.from_env()
    result = client.post_thread(
        [copy["main"], copy["reply1"], copy["reply2"]],
        images=paths,
        alt_text=copy["alt_text"],
    )
    return {
        "url": bluesky_client.public_url(result["root"]["uri"], client.handle),
        "bluesky_uri": result["root"]["uri"],
        "bluesky_cid": result["root"]["cid"],
        "reply_uris": [post["uri"] for post in result["replies"]],
        "images": [path.name for path in paths],
        "language": "en",
    }
