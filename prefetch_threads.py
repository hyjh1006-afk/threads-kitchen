# -*- coding: utf-8 -*-
"""앞으로 발행될 레시피의 영어 스레드를 미리 만들어 캐시에 저장한다.

왜 필요한가 (2026-08-16 사고):
  Gemini 무료 등급은 모델·프로젝트당 하루 20회다. 그런데 발행 워크플로는
  실패할 때마다 15분 뒤 다시 시도하며 매번 새로 생성을 호출했고, 그 재시도가
  그날 쿼터를 전부 태워 3일간(8/14~8/16) 한 건도 발행되지 않았다.

  미리 캐시해 두면 매일의 발행은 Gemini 호출 0회로 끝난다 — 쿼터와 무관해진다.

주의: 이미지 생성(gemini-2.5-flash-image)은 모델별 한도가 따로지만 같은
  프로젝트를 쓴다. 이 스크립트는 이미지를 만들지 않는다(텍스트만) — 이미지가
  없는 메뉴는 발행 당일 생성되므로, 텍스트 사전 생성과 한도가 겹치지 않는다.

사용:
  python prefetch_threads.py              # 하루 한도 안에서 안전하게(기본 15건)
  python prefetch_threads.py --max-calls 5
  python prefetch_threads.py --dry-run    # 무엇이 필요한지만 확인 (호출 0회)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bluesky_thread_content as content
import publish_daily

BASE = Path(__file__).parent
CACHE_DIR = BASE / "bluesky_threads"
# 무료 한도 20회 중 일부는 그날 발행·수동 확인 몫으로 남긴다.
DEFAULT_BUDGET = 15


def cached(menu: dict) -> bool:
    path = CACHE_DIR / f"{menu['id']}.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return False
    return content._valid(data, menu["body"] + "\n" + menu["recipe"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-calls", type=int, default=DEFAULT_BUDGET,
                        help=f"이번 실행에서 쓸 Gemini 호출 상한 (기본 {DEFAULT_BUDGET})")
    parser.add_argument("--attempts", type=int, default=1,
                        help="메뉴당 재시도 횟수 (기본 1 — 쿼터 절약)")
    parser.add_argument("--dry-run", action="store_true", help="호출 없이 대상만 출력")
    args = parser.parse_args()

    order = publish_daily.publish_order()
    if not order:
        print("발행 대기열이 비어 있습니다 — menus.json 보충 필요")
        return 1

    pending = [menu for menu, _ in order if not cached(menu)]
    print(f"발행 대기열 {len(order)}건 · 캐시 있음 {len(order) - len(pending)}건 · 생성 필요 {len(pending)}건")
    for index, (menu, replaying) in enumerate(order, 1):
        mark = "캐시됨" if cached(menu) else "생성 필요"
        print(f"  {index:>2}. {menu['id']} {menu['name']} [{'재방송' if replaying else '신규'}] — {mark}")
    if args.dry_run or not pending:
        return 0

    budget = max(0, args.max_calls)
    made, failed = [], []
    exhausted = False
    for menu in pending:
        if budget <= 0:
            print(f"\n호출 예산 소진 — {menu['id']}부터는 다음 실행에서 이어서 (캐시는 그대로 남습니다)")
            break
        print(f"\n[{menu['id']}] {menu['name']} 생성 중…")
        data = None
        # 예산은 '실제 호출 수'로 깎는다 — 최악치를 미리 예약하면 남은 한도를 놀린다.
        for _ in range(max(1, args.attempts)):
            if budget <= 0:
                break
            budget -= 1
            data = content.generate(menu, attempts=1)
            if data or "429" in content.LAST_ERROR:
                break
            print(f"  재시도 — {content.LAST_ERROR}")
        if data:
            CACHE_DIR.mkdir(exist_ok=True)
            (CACHE_DIR / f"{menu['id']}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"  ✅ 저장 (reply2 {len(data['reply2'])}/{content.MAX_METHOD_CHARS}자)")
            made.append(menu["id"])
            continue
        print(f"  ❌ 실패: {content.LAST_ERROR}")
        failed.append((menu["id"], content.LAST_ERROR))
        if "429" in content.LAST_ERROR:
            print("  일일 쿼터 소진 — 여기서 중단합니다 (한도 초기화 후 다시 실행하세요)")
            exhausted = True
            break

    print(f"\n생성 {len(made)}건: {made or '없음'}")
    if failed:
        print("실패:")
        for menu_id, reason in failed:
            print(f"  - {menu_id}: {reason}")
    print(f"남은 호출 예산: {budget}")
    remaining = [menu["id"] for menu in pending if not cached(menu)]
    print(f"아직 캐시 없는 메뉴 {len(remaining)}건: {remaining or '없음'}")
    # 쿼터 소진은 '한도 초기화 후 재실행'이면 되는 정상 경로 — 워크플로를 빨간불로
    # 만들지 않는다. 캐시가 하나도 안 늘었는데 원인도 쿼터가 아니면 그때 실패로 본다.
    return 1 if (failed and not made and not exhausted) else 0


if __name__ == "__main__":
    sys.exit(main())
