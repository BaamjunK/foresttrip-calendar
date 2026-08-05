# 휴양림 빈자리 달력

숲나들e(foresttrip.go.kr) 전체 자연휴양림의 **숙박 시설 빈자리**를 매일 아침 조회해서,
월별 달력(GitHub Pages)에 어느 지점이 예약 가능한지 표시한다.

- 조회 범위: 오늘 ~ **다음 달 말일** (달력 탭 2개월)
- 카테고리: 숙박(01)만 — 캠핑/야영(02)은 제외
- 필터: 지역(시·도) / 운영주체(국립·공립·사립) / 정원 범위(인) / 1박 요금 범위(만원) / 휴양림명
  · 정원은 객실 정원 기준 범위다("2~4인"이면 정원이 그 사이인 객실만) — 하한만
  걸면 대형 객실까지 전부 걸려 필터 구실을 못 한다.
  · 조건을 통과한 객실이 없는 지점은 그 날짜에서 빠지고, 요금 조건이 걸리면
  "가격 미확인" 객실은 제외된다(판정 불가). 최소·최대를 거꾸로 넣으면 자동 교환.
- 상세 팝업: 객실별 요금·정원·면적, 휴양림명 클릭 시 숲나들e 예약 화면(해당 지점·날짜)으로 이동,
  카카오맵·네이버지도 바로가기, 예약 오픈 규칙
- 예약 오픈일: "매월 N일 오픈" 규칙인 휴양림을 달력에 🔔 로 표시. 날짜를 열면
  그날 오픈되는 휴양림이 운영주체·지역·예약 링크와 함께 나온다(오픈일은 접수
  시작일이라 링크에 숙박 날짜를 싣지 않고 지점 예약 화면만 연다)
- 조회 엔진: https://github.com/NomaDamas/k-skill/tree/main/foresttrip-vacancy 스크립트를 `vendor/` 에 vendoring (MIT, 로컬 패치 2건 — 파일 상단 주석 참고)

## 라이선스

이 저장소의 코드는 MIT 라이선스다([LICENSE](LICENSE)).

`vendor/run_foresttrip_vacancy.py` 는 [NomaDamas/k-skill](https://github.com/NomaDamas/k-skill)
의 foresttrip-vacancy 스크립트를 가져온 것으로, 원본도 MIT 라이선스다. MIT 가 요구하는
저작권·허가 고지는 [vendor/LICENSE](vendor/LICENSE) 에 원문 그대로 보존했다.

## 구조

```
deploy.sh                  일배치 진입점: 조회 → 가격 → 정책 → 변환 → 커밋 → 푸시
vendor/run_foresttrip_vacancy.py   k-skill 조회 스크립트 (Playwright 로그인 + JSON 조회)
batch/fetch_prices.py      객실별 1박 요금 조회 (조합별 1회 호출 + 영구 캐시)
batch/fetch_policy.py      예약 오픈 정책 페이지 파싱 (공개 페이지)
batch/transform.py         raw JSON + 정책 → docs/data/vacancy.json 변환
docs/index.html            달력 페이지 (GitHub Pages, 정적/의존성 없음)
docs/data/vacancy.json     달력이 읽는 데이터 (배치가 갱신, schema v2 · 약 700KB)
launchd/…plist             매일 08:00 자동 실행 등록용
data/                      raw.json, price_cache.json, launchd.log (git 제외)
```

동작 원리:
- **빈자리**: 월별예약조회 엔드포인트는 로그인 없이는 401. vendor 스크립트가
  Playwright(headless chromium)로 로그인해 CSRF 토큰·쿠키를 얻고(10분 세션 캐시)
  지점×날짜 범위를 JSON 으로 조회한다. "(예비)" 객실과 중복 행은 자동 제거.
- **지역**: API 응답의 지역 필드(insttAreaNm)가 항상 비어 있어, 로그인 시 시·도
  드롭다운을 순회할 때 지점→시·도 매핑을 세션에 같이 저장한다(vendor 패치).
- **가격**: 가격 API 는 객실×날짜 단위지만 요금은 (객실, 시즌, 주중/주말) 조합으로
  결정되므로 조합별 1회만 호출하고 `data/price_cache.json` 에 영구 캐시한다.
  일일 호출 상한(기본 1500, env `PRICE_CALL_CAP`) 초과분은 "가격 미확인"으로
  남고 다음 배치가 이어서 채운다.
- **예약 오픈일**: 예약 정책 페이지(공개)를 파싱해 "매월 N일 HH시 오픈" 규칙을
  추출한다. 고정일이 있는 곳은 달력 셀에, 규칙 전문은 상세 팝업에 표시.
  정책 표와 조회 데이터의 지점명 표기가 달라(`[공립](광양시)백운산자연휴양림` vs
  `광양백운산자연휴양림`) 운영주체·시·군·구·이름을 단계적으로 좁혀 매칭하고,
  확정하지 못하면 규칙을 감춘다(틀린 오픈일 표시 방지).
- **예약 링크**: 휴양림명을 누르면 `fcfsRsrvtPssblGoodsDetls.do` 에 지점 ID와
  선택 날짜(1박)를 실어 보낸다. `_csrf` 와 `netfunnel_key` 는 붙이지 않는다 —
  세션마다 다른 값이라 무효이고, 없어도 로그인 상태면 정상 동작한다(대기열이
  걸려 있으면 숲나들e 가 대기 화면을 띄운다). 비로그인 시 로그인 후 이어진다.
- **운영주체**: 지점명 앞의 `[국립]`/`[공립]`/`[사립]` 이 그대로 필터가 된다
  (조회 결과 기준 국립 41 · 공립 121 · 사립 11곳). 국립은 예약 오픈이 "선착순
  6주 전 수요일 / 추첨제"라 매월 고정일이 없어 달력의 🔔 오픈 마커에는 잡히지
  않는다 — 빈자리 자체는 다른 곳과 똑같이 표시된다.
- **데이터 구조(schema v2)**: 매일 커밋되는 파일이라 중복을 걷어낸 인덱스 참조형이다.
  지점·객실·유형을 마스터 배열로 빼고 날짜별로는 `[[지점idx, [[객실idx, 요금], …]], …]`
  만 남긴다. 같은 객실 정의가 58일 내내 되풀이되던 구조(5.3MB)를 700KB(gzip 98KB)로
  줄였다. 요금 0 은 "가격 미확인", 정원·면적 0 은 값 없음을 뜻한다. 페이지는 `v` 를
  확인하고 다르면 로드를 거부하니, 스키마를 바꿀 때는 `transform.py` 와
  `docs/index.html` 을 같은 커밋으로 배포해야 한다.

## 최초 설정

### 1. 실행 환경

```bash
cd ~/code/foresttrip-calendar
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

### 2. 숲나들e 자격증명 (직접 만들 것 — 채팅/셸 히스토리에 남기지 않기)

```bash
mkdir -p ~/.config/k-skill
touch ~/.config/k-skill/secrets.env
chmod 600 ~/.config/k-skill/secrets.env
```

에디터로 열어 두 줄 입력:

```
KSKILL_FORESTTRIP_ID=<숲나들e 아이디>
KSKILL_FORESTTRIP_PASSWORD=<비밀번호>
```

### 3. GitHub 저장소 + Pages

```bash
cd ~/code/foresttrip-calendar
gh repo create foresttrip-calendar --public --source . --push
gh api -X POST repos/{owner}/foresttrip-calendar/pages -f 'source[branch]=main' -f 'source[path]=/docs'
```

(또는 저장소 Settings → Pages → Branch `main` / 폴더 `/docs`)

### 4. 첫 실행 확인 후 launchd 등록

```bash
./deploy.sh --no-push        # 조회~커밋까지 동작 확인
git push                     # 첫 배포는 수동으로
```

```bash
sed -e "s|__PROJECT_DIR__|$PWD|g" -e "s|__HOME__|$HOME|g" \
  launchd/com.foresttrip-calendar.plist > ~/Library/LaunchAgents/com.foresttrip-calendar.plist
launchctl load ~/Library/LaunchAgents/com.foresttrip-calendar.plist
```

이후 매일 08:00 에 자동 갱신·푸시된다. 로그: `data/launchd.log`

## 운영 메모

- `docs/data/vacancy.json` 의 `sample: true` 는 첫 배치 전 샘플 데이터 표시용 —
  실제 배치가 돌면 사라진다.
- 일부 지점 조회 실패(`fetch_failures > 0`)여도 배포는 진행하고, 페이지 상단에
  경고 배너로 표기한다. 전체 실패 시에는 세션을 갈아 1회 재시도 후 중단한다.
- 조회는 읽기 전용이다. 예약·결제는 하지 않으며, 실제 예약은 숲나들e에서 직접 한다.
- 동시성은 3 으로 낮춰 두었다(사이트 부하 배려, 최대 5).
