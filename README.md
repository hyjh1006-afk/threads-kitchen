# 🍚 threads-kitchen — 스레드 집밥 공장 (쿠팡파트너스)

집밥 메뉴 추천 글(사진 포함)을 스레드에 올리고, **답글에 레시피 + 재료 쿠팡파트너스 링크**를
자동으로 다는 프로그램. (ai_monetization_lab 실험 E5)

검증된 패턴을 따른다: 본문에 링크 금지(도달률↓) → 답글에 링크, 사진 필수, 공정위 문구 상단.

## 동작 방식 — 완전 자동 (사용자 승인 2026-07-26)

**GitHub Actions가 매일 11:20 KST경 자동 실행** (무료 러너 특성상 최대 1시간여 지연 가능):

```
메뉴 선택 → Gemini로 음식 사진 생성 → GitHub 푸시(호스팅) → URL 검증
→ 쿠팡 링크 생성 → [광고] 태그 본문 게시 → 45초 후 답글(공정위 문구+레시피+링크)
→ 사용한 메뉴 기록 커밋
```

- 하루 1개 원칙 (이중 실행 방지 잠금 포함). 스팸성 대량 게시 금지.
- 링크 생성 실패한 재료 줄은 자동 생략 (자리 문구가 게시되는 사고 방지)
- 이미지 실패 시 텍스트-온리로 진행. Threads 토큰 없으면 조용히 건너뜀.
- **끄기**: config.json의 `"auto_post": false` → 승인형 수동 모드로 복귀:
  `python make_draft.py` (초안 확인) → `python post_approved.py --yes`
- 문체·구성 기준: STYLE_GUIDE.md (성공 사례 분석 + 공정위 2026 규정)

## 연결 1회 설정 (사용자가 직접 — 계정 관련)

### A. Threads API 토큰
1. https://developers.facebook.com → 앱 만들기 → 사용 사례에서 **Threads API** 추가
2. 앱의 Threads 설정에서 본인 스레드 계정 연결(권한: threads_basic, threads_content_publish)
3. 장기 액세스 토큰(60일) 발급 → 아래 .env에 저장
4. 사용자 ID 확인: `GET https://graph.threads.net/v1.0/me?access_token=...`

### B. 쿠팡파트너스 키
- partners.coupang.com → 도구 → Open API → 키 발급
- `.env`에 넣거나 `coupang_keys.txt`(1줄 Access, 2줄 Secret)로 저장
- ⚠ 파트너스 콘솔에서 **활동 채널에 스레드 계정 등록**이 필요한지 확인할 것 (정책 준수)

### C. Gemini 키 (이미지 자동 생성 — 무료)
1. https://aistudio.google.com 에서 **새 구글 클라우드 프로젝트로** API 키 발급
   ⚠ 반드시 전용 프로젝트로 만들 것 — 무료 한도는 프로젝트 단위라 Blogger_auto 키를
   같이 쓰면 서로 한도를 갉아먹는다 (실측: 공유 키로 429 발생 확인, 과거 동일 사고 이력)
2. `.env`에 `GEMINI_API_KEY=` 입력. 모델: gemini-2.5-flash-image (무료 등급 이미지 생성)
- 키가 없거나 실패하면 자동으로 텍스트-온리 게시로 폴백 (게시가 막히지 않음)

### D. 이미지 호스팅 (스레드는 공개 URL만 받음 — 1회 설정 후 전자동)
1. 이 폴더를 GitHub 저장소로 만들기: github.com에서 threads-kitchen 저장소(Public) 생성 후
   `git init` → `git remote add origin ...` → 최초 push
2. config.json의 `image_base_url`에 raw 주소 입력:
   `https://raw.githubusercontent.com/<계정>/threads-kitchen/main/images`
3. 이후에는 make_draft가 이미지 생성→커밋→푸시→URL 검증까지 알아서 한다

### E. GitHub Secrets 등록 (자동 실행용 — 마지막 단계)
저장소 → Settings → Secrets and variables → Actions → New repository secret으로 5개 등록:
`THREADS_USER_ID` / `THREADS_ACCESS_TOKEN` / `COUPANG_ACCESS_KEY` / `COUPANG_SECRET_KEY` / `GEMINI_API_KEY`

등록 후 Actions 탭 → daily-threads-kitchen → **Run workflow**로 첫 게시를 수동 트리거해
정상 동작을 확인하면 끝 — 이후 매일 11:20 KST경 자동.

⚠ 시크릿 편집 전엔 전체 백업 습관 (과거 시크릿 유실 사고 이력)

### 로컬 수동 실행용 .env (.env는 git에 올리지 않음)
```
THREADS_USER_ID=
THREADS_ACCESS_TOKEN=
COUPANG_ACCESS_KEY=
COUPANG_SECRET_KEY=
GEMINI_API_KEY=
```

## 소재 은행 (menus.json)

메뉴 15개 준비됨. 각 항목: 본문(훅) / 답글 레시피 / 재료 쿠팡 검색어 / 이미지 프롬프트.
추가·수정은 JSON만 고치면 된다. 다 쓰면 새 메뉴를 요청할 것.

## 성과 측정 → 랩 기록

- 노출·조회: 스레드 앱 인사이트 (Phase 2에서 API 자동 수집 예정)
- 수익: 파트너스 리포트의 확정 수수료만 VERIFIED로 랩(데이터 입력)에 기록. subId=threads_kitchen으로 구분
- 실험 E5 중단 기준: 클릭 100회에도 전환 0이면 상품군 변경

## 준수 사항

- 공정위 대가성 문구는 답글 상단에 자동 포함된다 — 지우지 말 것
- 하루 1~2개, 같은 내용 도배 금지 (스레드 스팸 정책 + 우리 원칙)
- 레시피는 자체 작성 콘텐츠 (외부 레시피 복붙 금지)
- 토큰 60일 만료 주의 — 만료 시 재발급 (달력 알림 권장)
