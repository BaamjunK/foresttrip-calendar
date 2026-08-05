#!/usr/bin/env python3
"""정기 오픈일이 있는 휴양림이 월추첨제를 함께 운영하는지 확인한다.

사용법: fetch_lottery.py <policy.json> <directory.json> <out.json>

왜 필요한가
- 정책 표의 "매월 N일 09시 오픈"은 그 날짜에 접수가 시작된다는 것만 알려주고,
  그것이 선착순 오픈인지 추첨 신청 시작인지는 구분해 주지 않는다. 표의
  선착순/추첨 칸도 실제와 어긋난다(강씨봉·석모도는 추첨 칸에 값이 있지만
  지점 페이지에는 추첨이 없고, 반대로 안면도는 추첨을 실제로 운영한다).
- 그래서 지점 소개 페이지(selectFcltSrchView.do)를 직접 보고 "추첨" 운영
  흔적이 있는 곳만 골라낸다. 로그인 없이 열리는 공개 페이지다.

출력
  {
    "generated_at": "...",
    "checked": 56, "failed": 3,
    "lottery_ids": ["ID02030031", ...]   # 추첨 병행으로 판정된 지점 ID
  }

조회 실패는 그 지점을 "판정 불가"로 두고 목록에서 제외한다(추첨이 아니라고
단정하지 않되, 배지를 붙이지도 않는다). 전체가 실패하면 종료 코드 1 —
deploy.sh 는 기존 파일을 유지한다.
"""
from __future__ import annotations

import concurrent.futures
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
FCLT_URL = (
    "https://www.foresttrip.go.kr/pot/is/fs/selectFcltSrchView.do"
    "?hmpgId=FRIP&menuId=002001&insttId="
)
CONCURRENCY = 4


def strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def norm(name: str) -> str:
    return re.sub(r"\s+", "", name)


def bare(name: str) -> str:
    """"[공립](노원구)수락산동막골자연휴양림" → "수락산동막골자연휴양림"."""
    return re.sub(r"^\s*\([^)]*\)\s*", "", re.sub(r"^\s*\[[^\]]*\]\s*", "", name)).strip()


def check(instt_id: str) -> bool | None:
    """추첨 운영 흔적이 있으면 True, 없으면 False, 조회 실패면 None."""
    request = urllib.request.Request(
        FCLT_URL + instt_id,
        headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = strip_tags(response.read().decode("utf-8", "replace"))
    except Exception:
        return None
    # 페이지에 "추첨"이 등장하면 그 휴양림이 추첨을 운영한다는 신호다
    # (배지·안내문·공지 제목 어디에 나오든 마찬가지).
    return "추첨" in text


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: fetch_lottery.py <policy.json> <directory.json> <out.json>", file=sys.stderr)
        return 2
    with open(sys.argv[1], encoding="utf-8") as f:
        policies = json.load(f)
    with open(sys.argv[2], encoding="utf-8") as f:
        directory = json.load(f)

    by_name = {norm(bare(name)): fid for name, fid, _region in directory}
    # 달력이 🔔 로 표시하는 대상 = 매월 고정 오픈일이 있는 휴양림
    targets: dict[str, str] = {}
    for policy in policies:
        if not policy.get("open_day"):
            continue
        fid = by_name.get(norm(policy["name"]))
        if fid:
            targets[fid] = policy["name"]
    if not targets:
        print("확인 대상이 없습니다(정책·지점 목록 확인 필요)", file=sys.stderr)
        return 1

    ids = sorted(targets)
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        results = list(pool.map(check, ids))

    lottery = [fid for fid, hit in zip(ids, results) if hit is True]
    failed = sum(1 for hit in results if hit is None)
    if failed == len(ids):
        print(f"전체 조회 실패({failed}곳) — 기존 결과를 유지하세요", file=sys.stderr)
        return 1

    payload = {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "checked": len(ids) - failed,
        "failed": failed,
        "lottery_ids": lottery,
    }
    with open(sys.argv[3], "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    names = [targets[fid] for fid in lottery]
    print(
        f"추첨 병행 {len(lottery)}곳 / 확인 {payload['checked']}곳"
        + (f" (조회 실패 {failed}곳)" if failed else "")
        + (": " + ", ".join(names[:6]) + ("…" if len(names) > 6 else "") if names else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
