# -*- coding: utf-8 -*-
"""오늘의 초안 생성 (게시는 하지 않음 — 승인형 워크플로 1단계).

사용: python make_draft.py [--menu m03]
결과: drafts/YYYY-MM-DD.json + 화면에 미리보기 출력
"""
import argparse
import json
from datetime import date
from pathlib import Path

import coupang_link
import image_gen
import image_host

BASE = Path(__file__).parent
CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
MENUS_PATH = BASE / "menus.json"


def pick_menu(menu_id: str | None = None) -> dict | None:
    data = json.loads(MENUS_PATH.read_text(encoding="utf-8"))
    for m in data["menus"]:
        if menu_id and m["id"] == menu_id:
            return m
        if not menu_id and not m.get("used"):
            return m
    return None


def with_ad_tag(body: str) -> str:
    """본문 [광고] 태그 — 사용자 결정(2026-07-27)으로 기본 OFF (config로 복귀 가능)."""
    if not CONFIG.get("ad_tag_in_body", False):
        return body
    tag = CONFIG.get("ad_tag", "[광고]")
    return body if body.startswith(tag) else f"{tag} {body}"


def build_reply(menu: dict, include_missing: bool = True) -> tuple[str, list[dict]]:
    """답글 텍스트: 공정위 문구 상단 → 레시피 → 재료 링크.

    include_missing=False(자동 모드): 링크 생성 실패한 재료 줄은 아예 뺀다
    (자리 표시 문구가 실제 게시되는 사고 방지).
    안내문구 위치는 config.disclosure_position: reply_top | reply_bottom(사용자 결정).
    """
    lines = [menu["recipe"], ""]
    links = []
    for ing in menu["ingredients"]:
        item = coupang_link.search_link(ing["search"], CONFIG.get("coupang_subid", "threads_kitchen"))
        if item:
            lines.append(f"🛒 {ing['label']}: {item['url']}")
            links.append({"label": ing["label"], **item})
        elif include_missing:
            lines.append(f"🛒 {ing['label']}: [링크 자리 — 파트너스 키 설정 후 자동 생성]")
            links.append({"label": ing["label"], "url": None, "note": "키 미설정 또는 검색 실패"})
    if CONFIG.get("disclosure_position", "reply_bottom") == "reply_top":
        lines.insert(0, CONFIG["disclosure"] + "\n")
    else:
        lines += ["", CONFIG["disclosure"]]
    return "\n".join(lines).rstrip(), links


def ensure_image(menu: dict) -> str | None:
    """이미지 자동 파이프라인: 생성(Gemini) → git push 호스팅 → 공개 URL 검증.

    어느 단계가 실패해도 None을 반환하고 텍스트-온리로 진행한다.
    """
    local = BASE / "images" / f"{menu['id']}.png"
    if not local.exists():
        if not image_gen.is_configured():
            print("  (GEMINI_API_KEY 없음 — 텍스트로 진행)")
            return None
        print(f"  이미지 생성 중… ({menu['id']}.png)")
        if not image_gen.generate(menu["image_prompt"], local,
                                  CONFIG.get("image_model", "gemini-2.5-flash-image")):
            return None
    image_base = CONFIG.get("image_base_url", "").strip().rstrip("/")
    if not image_base:
        print(f"  (이미지 로컬 생성됨: {local.name} — 호스팅하려면 config의 image_base_url 설정)")
        return None
    if not image_host.push_images():
        print("  (이미지 푸시 실패/원격 없음 — 텍스트로 진행)")
        return None
    url = f"{image_base}/{menu['id']}.png"
    if not image_host.verify_url(url):
        print(f"  (공개 URL 확인 실패: {url} — 텍스트로 진행)")
        return None
    return url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--menu", default=None, help="특정 메뉴 id 지정 (예: m13)")
    args = ap.parse_args()

    menu = pick_menu(args.menu)
    if not menu:
        print("소재 은행이 비었습니다 — menus.json에 메뉴를 추가하세요.")
        return

    image_url = ensure_image(menu)

    reply_text, links = build_reply(menu)
    draft = {
        "date": date.today().isoformat(),
        "menu_id": menu["id"],
        "menu_name": menu["name"],
        "body_text": with_ad_tag(menu["body"]),
        "image_url": image_url,
        "image_prompt": menu["image_prompt"],
        "reply_text": reply_text,
        "links": links,
        "status": "PENDING_APPROVAL",
    }
    out = BASE / "drafts" / f"{draft['date']}.json"
    out.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 46)
    print(f"[초안] {menu['name']}  ({out.name})")
    print("=" * 46)
    print("\n--- 본문 ---\n" + draft["body_text"])
    print("\n--- 이미지 ---")
    print(image_url if image_url else "(텍스트-온리 게시 — 이미지 파이프라인 미완성 시 자동 폴백)")
    print("\n--- 답글 ---\n" + reply_text)
    print("\n검토 후 게시하려면:  python post_approved.py --yes")


if __name__ == "__main__":
    main()
