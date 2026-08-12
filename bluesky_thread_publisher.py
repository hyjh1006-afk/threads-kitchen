# -*- coding: utf-8 -*-
"""Publish one English recipe as a root post followed by two replies."""
from __future__ import annotations

from pathlib import Path

import bluesky_client
import bluesky_thread_content
import coupang_link
import image_gen

BASE = Path(__file__).parent


def affiliate_offer(menu: dict, config: dict) -> dict:
    """Find one relevant, short Coupang affiliate link or stop publishing."""
    affiliate = config.get("affiliate") or {}
    sub_id = str(affiliate.get("sub_id") or "bluesky_recipe")
    for ingredient in menu.get("ingredients") or []:
        item = coupang_link.search_link(str(ingredient["search"]), sub_id)
        url = str((item or {}).get("url") or "")
        if url.startswith("https://") and len(url) <= 100:
            return {"label": ingredient["label"], "url": url}
    raise RuntimeError("A short Coupang affiliate link could not be generated; publishing stopped.")


def monetized_reply(method_text: str, offer: dict, config: dict) -> str:
    affiliate = config.get("affiliate") or {}
    disclosure = str(affiliate.get("disclosure") or "").strip()
    if not disclosure:
        raise RuntimeError("Affiliate disclosure is missing from publisher_config.json.")
    text = f"{method_text.strip()}\n\n{disclosure}\n🛒 Featured ingredient: {offer['url']}"
    if len(text) > 300:
        raise RuntimeError(f"Monetized Bluesky reply is too long ({len(text)}/300).")
    return text


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
    offer = affiliate_offer(menu, config)
    final_reply = monetized_reply(copy["reply2"], offer, config)
    paths = local_images(menu, generate=generate_images)
    client = bluesky_client.BlueskyClient.from_env()
    result = client.post_thread(
        [copy["main"], copy["reply1"], final_reply],
        images=paths,
        alt_text=copy["alt_text"],
        links=["", "", offer["url"]],
    )
    return {
        "url": bluesky_client.public_url(result["root"]["uri"], client.handle),
        "bluesky_uri": result["root"]["uri"],
        "bluesky_cid": result["root"]["cid"],
        "reply_uris": [post["uri"] for post in result["replies"]],
        "images": [path.name for path in paths],
        "language": "en",
        "affiliate": offer,
    }
