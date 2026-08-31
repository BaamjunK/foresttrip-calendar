#!/usr/bin/env python3
"""전 지점의 객실 구성(프로파일)을 모아 data/profiles.json 에 저장한다.

사용법: fetch_profiles.py <directory.json> <out.json> [--days 3]

왜 따로 수집하나
- 일반 조회 결과에는 "빈자리가 있는" 객실만 남는다. 그래서 만실 지점(수락산
  동막골·광치 등)은 객실 구성을 알 수 없는데, 하필 그런 곳이 가장 인기 있는
  휴양림이다. 좋은 곳의 특징을 따지려면 이들도 봐야 한다.
- 월별조회 응답은 예약 불가(OVER_DATE·N) 객실도 행으로 돌려준다. 짧은 기간만
  조회해 "이 지점에 어떤 객실이 있는가" 만 뽑는다(빈자리 여부는 보지 않는다).

프로파일 항목 (숙박 시설만 — 캠핑은 성격이 달라 따로 센다)
  stay   숙박 고유 객실 수
  detach 그중 독채(숲속의집·통나무집·개별동·트리하우스 등) 수
  cap    정원 중간값
  area   면적 중간값(㎡)
  camp   캠핑 고유 사이트 수
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor"))
import run_foresttrip_vacancy as v  # noqa: E402

# transform.py 와 같은 규칙을 쓴다(한쪽만 바뀌면 분류가 어긋난다)
DETACHED_RE = re.compile(
    r"(집|하우스|house|통나무|트리|카라반|글램핑|이동식|독채|펜션|방갈로|코티지"
    r"|산막|산장|가옥|주택|개별동)", re.I
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    ap.add_argument("out")
    ap.add_argument("--days", type=int, default=3)
    args = ap.parse_args()

    directory = json.loads(Path(args.directory).read_text(encoding="utf-8"))
    today = date.today()
    start = today.strftime("%Y%m%d")
    end = (today + timedelta(days=args.days)).strftime("%Y%m%d")

    cache = Path("~/.cache/k-skill/foresttrip-vacancy/session.json").expanduser()
    sess = v.load_session_cache(cache)
    if sess is None:
        sess = v.bootstrap_session(
            forest_id=v.require_env("KSKILL_FORESTTRIP_ID"),
            forest_pw=v.require_env("KSKILL_FORESTTRIP_PASSWORD"),
        )
        v.save_session_cache(cache, sess)

    out: dict[str, dict] = {}
    failed = 0
    for name, fid, _region in directory:
        stay: set = set()
        detach: set = set()
        camp: set = set()
        caps: list[int] = []
        areas: list[int] = []
        got = False
        for cat in ("01", "02"):
            _, _, data, err = v.fetch_one(
                session=sess, forest_id=fid, category=cat, today=start, last_day=end
            )
            if err or not data:
                continue
            got = True
            for row in data:
                key = (row.get("goodsNm") or "", row.get("goodsClsscNm") or "")
                if cat == "02":
                    camp.add(key)
                    continue
                if v.is_reserve_room(row):   # "(예비)" 객실은 운영자용
                    continue
                stay.add(key)
                if DETACHED_RE.search((row.get("goodsClsscNm") or "").replace(" ", "")):
                    detach.add(key)
                try:
                    if row.get("mxmmAccptCnt"):
                        caps.append(int(row["mxmmAccptCnt"]))
                except (TypeError, ValueError):
                    pass
                m = re.search(r"\d+", str(row.get("insttArea") or ""))
                if m:
                    areas.append(int(m.group()))
        if not got:
            failed += 1
            continue
        out[fid] = {
            "stay": len(stay),
            "detach": len(detach),
            "camp": len(camp),
            "cap": round(statistics.median(caps)) if caps else 0,
            "area": round(statistics.median(areas)) if areas else 0,
        }

    Path(args.out).write_text(
        json.dumps({"generated_at": start, "profiles": out}, ensure_ascii=False),
        encoding="utf-8",
    )
    with_stay = sum(1 for p in out.values() if p["stay"])
    print(f"지점 프로파일 {len(out)}곳(숙박 있는 곳 {with_stay}) · 조회 실패 {failed}곳")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
