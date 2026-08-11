# 🍚 threads-kitchen — 집밥 레시피 공장

매일 집밥 레시피를 **WordPress.com에 긴 글로 발행**하고, **Bluesky에 사진과 링크로 홍보**하는 자동화다. 쿠팡 파트너스 링크와 광고 표기를 포함한다.

## 현재 운영 채널

- WordPress: https://pparkzzekitchen.wordpress.com/
- Bluesky: https://bsky.app/profile/pparkzze.bsky.social
- 발행 시각: 매일 11:20 KST (`schedule.json`, 파이프라인 HQ에서 변경 가능)
- 실행 워크플로: `.github/workflows/daily-recipe-publisher.yml`

> 2026-08-11 기존 Threads 계정이 삭제되어 Threads 운영은 종료했다. 과거 구현 파일은 기록용으로 남기되, `daily.yml`은 게시를 수행하지 않는 종료 안내 워크플로다.

## 발행 흐름

```text
메뉴 선택 → 근거 기반 긴 레시피 작성 → 음식 사진 준비
→ WordPress 미디어·본문 발행 → Bluesky 사진+링크 홍보
→ 발행 상태와 채널 실측 지표를 GitHub에 저장
```

- `m01`~`m15` 과거 메뉴를 하루 1개씩 먼저 WordPress에 재발행한 뒤 새 메뉴로 넘어간다.
- 하루 상한은 `publisher_config.json`의 `posting.per_day`가 최종 방어한다.
- WordPress 발행 성공 후 Bluesky 홍보가 실행되며, Bluesky 실패는 WordPress 본문을 되돌리지 않는다.
- 공정위 대가성 문구는 게시물에 포함하며, 수익은 VERIFIED만 별도 랩에 기록한다.

## 필요한 GitHub Actions Secrets

```text
WORDPRESS_SITE
WORDPRESS_ACCESS_TOKEN
BLUESKY_HANDLE
BLUESKY_APP_PASSWORD
COUPANG_ACCESS_KEY
COUPANG_SECRET_KEY
GEMINI_API_KEY
```

로컬에서는 같은 이름을 `.env`에 둔다. `.env`와 `.local-secrets/`는 커밋하지 않는다.

## 실측 지표

`collect_channel_metrics.py`가 플랫폼 API에서 실제 제공되는 숫자만 수집해 `state/channel_metrics.json`에 저장한다.

- WordPress: 발행 글, 누적/오늘/최근 7일 조회, 최근 7일 방문자, 팔로워
- Bluesky: 게시물, 팔로워, 팔로잉, 최근 원문 최대 100개의 좋아요·재게시·답글·인용 합계
- Bluesky는 일반 게시물 조회수를 공개하지 않으므로 조회수를 추정하지 않는다.

AI 사옥과 파이프라인 HQ는 이 상태 파일을 함께 읽는다. WordPress OAuth 토큰은 발행 저장소 밖으로 복제하지 않는다.

## 주요 파일

- `publish_daily.py` — 하루 발행 진입점
- `blog_recipe_publisher.py` — 긴 레시피 구성과 두 채널 발행
- `wordpress_com_client.py` — WordPress.com OAuth 클라이언트
- `bluesky_client.py` — Bluesky AT Protocol 클라이언트
- `collect_channel_metrics.py` — 관제용 실측 지표 수집
- `publisher_config.json` — 발행 상한·재생 순서·광고 문구
- `schedule.json` — KST 발행 시각
- `state/wordpress_published.json` — 발행 이력
- `state/channel_metrics.json` — 공유 지표

## 수동 확인

```powershell
python -m unittest discover -s tests -v
python collect_channel_metrics.py
python publish_daily.py
```

`publish_daily.py`는 오늘 상한을 이미 채웠으면 새 글을 발행하지 않는다. 특정 메뉴 재실행은 중복 발행 여부를 먼저 확인한다.