# 휴양림 빈자리 달력

숲나들e(foresttrip.go.kr) 전체 자연휴양림의 **숙박 시설 빈자리**를 매일 아침 조회해서,
월별 달력(GitHub Pages)에 어느 지점이 예약 가능한지 표시한다.

- 조회 범위: 오늘 ~ **다음 달 말일** (달력 탭 2개월)
- 카테고리: 숙박(01) + 캠핑/야영(02)
- 시설 구분: 독채 / 동형(여러 세대가 한 건물) / 캠핑 / 기타로 나눠 필터한다.
  캠핑은 조회 카테고리로 확실히 갈리지만, 숙박의 독채·동형은 유형명으로 추론한다
  (유형칸에 "가족·단체" 같은 이용대상이나 시설명이 들어오는 경우가 있어
  확신이 서는 이름만 분류하고 나머지는 기타로 둔다)
- 관심 휴양림: 상세 팝업의 ★ 로 등록하고 "⭐ 관심 N곳만" 으로 그 지점만 본다.
  필터 조건과 관심 목록은 브라우저(localStorage)에 남아 다음에 열 때 복원된다
  ("필터 초기화"는 보기 조건만 되돌리고 관심 목록은 유지)
- 링크 공유: "🔗 링크 복사"로 현재 조건(지역·주체·정원·요금·이름·관심 목록)을
  담은 주소를 만든다. 링크로 열면 그 조건이 그대로 재현되고, 주소의 조건이
  브라우저에 저장된 조건보다 우선한다
- 전체 휴양림 목록: "휴양림 N곳" 타일을 누르면 전 지점(186곳)이 뜬다. 그 기간
  빈자리가 없어 달력에 안 나오는 곳도 여기서 찾고 관심 등록할 수 있다
- 필터: 지역(시·도, 다중) / 운영주체(국립·공립·사립, 다중) / 숙박·캠핑(다중) /
  시설 세부(독채·동형·기타, 다중) / 정원 범위(인) / 1박 요금 범위(만원) / 휴양림명
  · 시설 세부는 숙박에만 있는 개념이라, 세부만 고르면("독채") 숙박으로 한정한다.
  캠핑까지 함께 보려면 숙박·캠핑에서 캠핑을 같이 고른다
  · 정원은 객실 정원 기준 범위다("2~4인"이면 정원이 그 사이인 객실만) — 하한만
  걸면 대형 객실까지 전부 걸려 필터 구실을 못 한다.
  · 조건을 통과한 객실이 없는 지점은 그 날짜에서 빠지고, 요금 조건이 걸리면
  "가격 미확인" 객실은 제외된다(판정 불가). 최소·최대를 거꾸로 넣으면 자동 교환.
- 상세 팝업: 객실별 요금·정원·면적, 휴양림명 클릭 시 숲나들e 휴양림 페이지로 이동,
  카카오맵·네이버지도 바로가기, 예약 오픈 규칙
- 예약 오픈일: "매월 N일 오픈" 규칙인 휴양림을 달력에 🔔 로 표시. 날짜를 열면
  그날 오픈되는 휴양림이 운영주체·지역·링크와 함께 나온다
- 지역 표기: "서울 노원구", "경기 가평"처럼 광역시/도 + 시·군·구로 줄여 보여준다
  (숲나들e 원본은 "서울/인천/경기"처럼 묶여 있어 어디인지 흐릿하다)
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
batch/fetch_lottery.py     오픈일 있는 지점의 추첨 병행 여부 판정 (지점 소개 페이지)
batch/transform.py         raw JSON + 정책 → docs/data/vacancy.json 변환
docs/index.html            달력 페이지 (GitHub Pages, 정적/의존성 없음)
docs/data/vacancy.json     달력이 읽는 데이터 (배치가 갱신, schema v2 · 약 700KB)
launchd/…plist             매일 08:00 자동 실행 등록용
data/                      raw.json, price_cache.json, directory.json, launchd.log (git 제외)
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
- **추첨 병행 판정**: 정책 표의 선착순/추첨 칸은 실제와 어긋난다(추첨 칸에 값이
  있는 강씨봉·석모도는 지점 페이지에 추첨이 없고, 안면도는 실제로 추첨을 운영한다).
  그래서 `fetch_lottery.py` 가 오픈일이 있는 지점의 소개 페이지를 매일 확인해
  "추첨" 운영 흔적이 있는 곳만 골라내고, 달력은 그 지점에만 "추첨 병행" 배지를
  붙인다. 확인 결과는 대체로 소수다(2026-08 기준 56곳 중 4곳: 안면도·원산도·
  용인·의왕바라산). 조회 실패한 지점은 배지를 붙이지 않는다(단정하지 않음).
  **정책 표의 오픈일이 어느 달 이용분인지는 어디에도 없다** — 그 회차가 이미
  마감됐는지는 달력으로 알 수 없어 안내문으로만 짚어 준다.
- **바깥에서 걸 수 있는 링크**: 예약 화면(`fcfsRsrvtPssblGoodsDetls.do`)으로 지점·
  날짜를 실어 보내는 딥링크는 쓸 수 없다. 숲나들e 가 Referer 를 검사해 자기
  사이트에서 온 요청이 아니면 **404** 를 준다(로그인 여부·날짜 유무와 무관).
  브라우저는 Referer 를 위조할 수 없고 `rel="noreferrer"` 로 지워도 404 다.
  대신 휴양림 소개 페이지 `selectFcltSrchView.do?insttId=<지점ID>` 로 보낸다 —
  Referer 를 가리지 않고 로그인도 필요 없으며 그 화면에 예약 버튼이 있다.
  지점 ID 는 로그인할 때 얻는 전 지점 목록(`data/directory.json`, 시·도 드롭다운을
  훑어 받은 186곳)에서 찾는다. 조회 결과에는 빈자리가 있는 지점만 남아서,
  이 목록이 없으면 "수락산 동막골"처럼 그 기간 빈자리가 없는 휴양림을 링크할 수
  없다. 그래도 못 찾으면 통합검색으로 폴백하는데, 검색은 등록 표기가 제각각이라
  마지막 수단이다("덕적도 자연휴양림" 1건인데 붙여 쓰면 0건, 반대 사례도 있다).
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
