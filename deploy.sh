#!/usr/bin/env bash
#
# 숲나들e 전체 휴양림 숙박(01) 빈자리 조회 → 달력 데이터 갱신 → 커밋 → GitHub Pages 배포(푸시).
#
#   ./deploy.sh              전체 실행 후 배포
#   ./deploy.sh --no-push    커밋까지만 (배포 안 함)
#
# launchd 자동 실행에서도 이 스크립트를 쓴다. 자격증명은 환경변수
# KSKILL_FORESTTRIP_ID / KSKILL_FORESTTRIP_PASSWORD 로 받고, 없으면
# ~/.config/k-skill/secrets.env (chmod 600) 에서 읽는다. 원문 ID/PW 를
# 이 저장소나 로그에 남기지 않는다.
set -uo pipefail
cd "$(dirname "$0")"

PUSH=1
for a in "$@"; do
  case "$a" in
    --no-push) PUSH=0 ;;
  esac
done

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*"; }

# ── 자격증명 ─────────────────────────────────────────────────────────
SECRETS_FILE="$HOME/.config/k-skill/secrets.env"
if [ -z "${KSKILL_FORESTTRIP_ID:-}" ] || [ -z "${KSKILL_FORESTTRIP_PASSWORD:-}" ]; then
  if [ -f "$SECRETS_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$SECRETS_FILE"
    set +a
  fi
fi
if [ -z "${KSKILL_FORESTTRIP_ID:-}" ] || [ -z "${KSKILL_FORESTTRIP_PASSWORD:-}" ]; then
  log "✗ 숲나들e 자격증명이 없습니다. $SECRETS_FILE 에 아래 두 줄을 만들어 주세요 (chmod 600):"
  log "    KSKILL_FORESTTRIP_ID=<아이디>"
  log "    KSKILL_FORESTTRIP_PASSWORD=<비밀번호>"
  exit 1
fi

# ── 인터프리터 (프로젝트 venv 고정) ──────────────────────────────────
PYTHON="${PYTHON:-$PWD/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
  log "✗ venv 가 없습니다. README 의 설치 절차를 먼저 실행하세요:"
  log "    python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python -m playwright install chromium"
  exit 1
fi

# ── 네트워크(DNS) 준비 대기 — 절전 복귀 직후 대비 (최대 5분) ─────────
NET_WAIT=0
until "$PYTHON" -c "import socket; socket.getaddrinfo('www.foresttrip.go.kr', 443)" >/dev/null 2>&1; do
  if [ "$NET_WAIT" -ge 300 ]; then
    log "✗ 네트워크(DNS) 준비 안 됨 — 5분 대기 후 중단. 다음 예정 시각에 재시도됩니다."
    exit 1
  fi
  [ "$NET_WAIT" -eq 0 ] && log "네트워크 준비 대기 중..."
  sleep 15
  NET_WAIT=$((NET_WAIT + 15))
done
[ "$NET_WAIT" -gt 0 ] && log "네트워크 준비 완료 (${NET_WAIT}s 대기)"

# ── 조회 범위: 오늘 ~ 다음 달 말일 ───────────────────────────────────
DATES=$("$PYTHON" - <<'PY'
import calendar
from datetime import date, timedelta

today = date.today()
nm_year, nm_month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
last = date(nm_year, nm_month, calendar.monthrange(nm_year, nm_month)[1])
days = (last - today).days
print(",".join((today + timedelta(d)).strftime("%Y%m%d") for d in range(days + 1)))
PY
)
log "조회 범위: ${DATES%%,*} ~ ${DATES##*,}"

# ── 조회 실행 (전체 휴양림, 숙박만) ──────────────────────────────────
mkdir -p data
run_fetch() {
  "$PYTHON" vendor/run_foresttrip_vacancy.py \
    --all --json --categories 01,02 --concurrency 3 --dates "$DATES" "$@" > data/raw.json
}

log "=== 숲나들e 조회 시작 ==="
run_fetch
RC=$?

# 종료코드 1 = 일부 지점 조회 실패(fetch_failures>0). JSON 자체가 유효하고
# 결과가 있으면 계속 진행하고, 결과가 비어 있으면 세션을 갈아 1회 재시도한다.
valid_result() {
  "$PYTHON" -c "
import json,sys
try:
    d = json.load(open('data/raw.json'))
except Exception:
    sys.exit(2)
sys.exit(0 if d.get('results') else 1)
"
}
if ! valid_result; then
  log "결과 없음/JSON 오류(rc=$RC) — 세션 갱신 후 1회 재시도"
  run_fetch --refresh-session
  RC=$?
  if ! valid_result; then
    log "✗ 재시도 후에도 결과가 없습니다(rc=$RC). 자격증명 또는 사이트 상태를 확인하세요."
    exit 1
  fi
fi
[ "$RC" -ne 0 ] && log "⚠ 일부 지점 조회 실패 — 페이지에 실패 건수로 표기됩니다."

# ── 전체 지점 디렉터리 ───────────────────────────────────────────────
# 로그인할 때 시·도 드롭다운을 훑어 얻은 전 지점 목록이 세션 캐시에 들어 있다.
# 조회 결과에는 빈자리가 있는 지점만 남으므로, 예약 오픈 목록처럼 빈자리가 없는
# 휴양림을 링크하려면 이 목록이 있어야 지점 ID 를 찾을 수 있다.
if ! "$PYTHON" - <<'PY'
import json, sys
from pathlib import Path
cache = Path("~/.cache/k-skill/foresttrip-vacancy/session.json").expanduser()
try:
    s = json.loads(cache.read_text(encoding="utf-8"))
except Exception:
    sys.exit(1)
sidos = s.get("sidos", {})
rows = [[nm, fid, sidos.get(fid, "")]
        for fid, nm in sorted(s.get("forests", {}).items(), key=lambda kv: kv[1])]
if not rows:
    sys.exit(1)
Path("data/directory.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
print(f"지점 디렉터리 {len(rows)}곳")
PY
then
  log "⚠ 지점 디렉터리 추출 실패 — 기존 파일로 진행"
fi

# ── 가격 부여 (조합별 1회 호출 + 영구 캐시, 실패해도 배포는 진행) ────
log "가격 조회(캐시 증분) 시작"
if ! "$PYTHON" batch/fetch_prices.py data/raw.json data/raw_priced.json; then
  log "⚠ 가격 조회 실패 — 가격 없이 진행"
  cp data/raw.json data/raw_priced.json
fi

# ── 예약 오픈 정책 수집 (공개 페이지, 실패 시 기존 파일 유지) ────────
log "예약 오픈 정책 수집"
if ! "$PYTHON" batch/fetch_policy.py data/policy.json; then
  log "⚠ 정책 수집 실패 — 기존 정책으로 진행"
fi

# ── 추첨 병행 여부 (오픈일 있는 지점의 공개 소개 페이지 확인) ─────────
# 정책 표의 선착순/추첨 칸은 실제와 어긋나므로 지점 페이지를 직접 본다.
log "추첨 병행 여부 확인"
if ! "$PYTHON" batch/fetch_lottery.py data/policy.json data/directory.json data/lottery.json; then
  log "⚠ 추첨 여부 확인 실패 — 기존 결과로 진행"
fi

# ── 카카오맵 평점 (국립·공립만, 오래된 것부터 조금씩) ────────────────
# 숲나들e 에는 평점이 없어 카카오맵에서 읽는다. 자주 바뀌지 않으니 14일 지난
# 것만, 하루 40곳까지만 본다(브라우저 렌더링이 필요해 지점당 2~3초 걸린다).
log "평점 수집(증분)"
if ! "$PYTHON" batch/fetch_ratings.py data/directory.json data/ratings.json \
     --max 40 --stale-days 14; then
  log "⚠ 평점 수집 실패 — 기존 평점으로 진행"
fi

# ── 변환 → docs/data/vacancy.json ───────────────────────────────────
if ! "$PYTHON" batch/transform.py data/raw_priced.json docs/data/vacancy.json \
     data/policy.json data/directory.json data/lottery.json data/ratings.json; then
  log "✗ 변환 실패 — 배포 중단"
  exit 1
fi

# ── 커밋 & 배포 ──────────────────────────────────────────────────────
# git diff 는 untracked 파일을 보지 못하므로(첫 실행 시 docs/ 전체가 untracked)
# status --porcelain 으로 변경·신규를 함께 감지한다.
if [ -z "$(git status --porcelain -- docs/)" ]; then
  log "변경 없음 — 커밋·배포 생략"
  exit 0
fi

# schema v2: days[날짜] = [[지점idx, [[객실idx, 요금], …]], …]
SUMMARY=$("$PYTHON" - <<'PY'
import json
d = json.load(open('docs/data/vacancy.json'))
days = d['days']
forests = {g[0] for v in days.values() for g in v}
priced = sum(1 for v in days.values() for g in v for s in g[1] if s[1])
slots = sum(len(g[1]) for v in days.values() for g in v)
print(f"{len(days)}일 / {len(forests)}개 지점 / 요금 {priced}/{slots}")
PY
)
[ -z "$SUMMARY" ] && SUMMARY="(요약 실패)"

git add docs/
if ! git commit -q -m "달력 갱신: 빈자리 $SUMMARY $(date '+%Y-%m-%d %H:%M')"; then
  log "✗ 커밋 실패 — 배포 중단"
  exit 1
fi
log "✓ 커밋 완료: $SUMMARY"

if [ "$PUSH" -eq 0 ]; then
  log "--no-push 지정 — 배포 생략 (수동: git push)"
  exit 0
fi

log "GitHub Pages 배포(푸시) 시작"
if git push -q origin HEAD; then
  log "✓ 배포 완료 (Pages 반영까지 1~2분)"
else
  rc=$?
  log "✗ 푸시 실패(rc=$rc). 커밋은 로컬에 남아 있으니 다음 실행 또는 수동 'git push' 로 반영됩니다."
  log "   인증 문제라면 확인: gh auth status --hostname github.com"
  exit "$rc"
fi
