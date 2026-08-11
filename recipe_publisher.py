# -*- coding: utf-8 -*-
"""Build one complete recipe article and an optional Bluesky teaser."""
from __future__ import annotations

import html
from pathlib import Path

import bluesky_client
import coupang_link
import image_gen
from wordpress_com_client import WordPressClient

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


def affiliate_links(menu: dict, sub_id: str) -> list[dict]:
    links = []
    for ingredient in menu.get("ingredients") or []:
        item = coupang_link.search_link(ingredient["search"], sub_id)
        if item and item.get("url"):
            links.append({"label": ingredient["label"], **item})
    return links


def _lines(text: str) -> str:
    return "<br>\n".join(html.escape(line) for line in text.splitlines())


def build_article(menu: dict, media: list[dict], links: list[dict], disclosure: str) -> str:
    gallery = ""
    if media:
        figures = []
        for item in media:
            url = html.escape(str(item.get("source_url") or ""), quote=True)
            if url:
                figures.append(
                    f'<figure class="wp-block-image"><img src="{url}" alt="{html.escape(menu["name"], quote=True)}"></figure>'
                )
        gallery = '<div class="wp-block-gallery has-nested-images columns-2">' + "".join(figures) + "</div>"

    link_section = ""
    if links:
        items = "".join(
            f'<li><a href="{html.escape(link["url"], quote=True)}" rel="sponsored nofollow">'
            f'{html.escape(link["label"])}</a></li>' for link in links
        )
        link_section = (
            "<hr><h2>사용한 재료·도구</h2>"
            f'<p><strong>{html.escape(disclosure)}</strong></p>'
            f"<ul>{items}</ul>"
        )

    return (
        f'<p class="recipe-intro">{_lines(menu["body"])}</p>'
        f"{gallery}<h2>레시피</h2>"
        f'<p class="recipe-steps">{_lines(menu["recipe"])}</p>'
        f"{link_section}"
    )


def teaser_text(menu: dict, url: str) -> str:
    hook = next((line.strip() for line in menu["body"].splitlines() if line.strip()), "")
    text = f"오늘은 {menu['name']} 🍚\n{hook}\n레시피는 여기 정리해뒀어👇\n{url}"
    return text if len(text) <= 300 else f"오늘은 {menu['name']} 🍚\n레시피는 여기👇\n{url}"[:300]


def publish(menu: dict, config: dict, *, generate_images: bool = True) -> dict:
    wordpress = WordPressClient.from_env()
    slug = f"home-recipe-{menu['id']}"
    existing = wordpress.find_post(slug)
    paths = local_images(menu, generate=generate_images)
    uploaded: list[dict] = []
    if not existing:
        for path in paths:
            try:
                uploaded.append(wordpress.upload_media(path, menu["name"]))
            except Exception as exc:
                print(f"[publisher] 이미지 제외({path.name}): {str(exc)[:160]}")
    links = affiliate_links(menu, config.get("coupang_subid", "recipe_blog"))
    article = build_article(menu, uploaded, links, config["disclosure"])
    post = existing or wordpress.publish(
        title=menu["name"], content=article, slug=slug,
        featured_media=(uploaded[0]["id"] if uploaded else None),
        excerpt=next((x for x in menu["body"].splitlines() if x.strip()), ""),
    )
    url = str(post.get("link") or "")
    result = {
        "wordpress_id": str(post.get("id") or ""), "url": url,
        "already_existed": bool(existing), "images": [p.name for p in paths],
        "links": [link["label"] for link in links],
        "bluesky_uri": None, "bluesky_error": None,
    }
    if config.get("bluesky", {}).get("enabled", True) and bluesky_client.is_configured():
        try:
            response = bluesky_client.BlueskyClient.from_env().post(
                teaser_text(menu, url), link=url, images=paths[:1],
                alt_text=f"{menu['name']} 완성 사진",
            )
            result["bluesky_uri"] = response.get("uri")
        except Exception as exc:
            result["bluesky_error"] = str(exc)[:300]
    return result
