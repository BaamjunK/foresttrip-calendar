#!/usr/bin/env python3
"""조회 스크립트의 raw JSON 을 달력 페이지가 읽는 vacancy.json 으로 변환한다.

사용법: python3 batch/transform.py data/raw.json docs/data/vacancy.json [data/policy.json]

policy.json(fetch_policy.py 산출물)이 주어지면 휴양림별 예약 오픈 규칙을
vacancy.json 의 "policies" 로 함께 실어 달력이 오픈일을 표시할 수 있게 한다.

raw 구조 (vendor/run_foresttrip_vacancy.py --json 출력):
  results[].forest / results[].dates[].use_dt / rooms[]

출력 구조 (달력 렌더러 전용):
  {
    "generated_at": "2026-08-03T08:00:00+09:00",
    "range": {"from": "20260803", "to": "20260930"},
    "forests_scanned": 170,
    "fetch_failures": 0,
    "days": {
      "20260815": [
        {"forest": "...", "region": "...", "rooms": [
          {"name": "...", "category": "...", "capacity": 4, "area": 23}
        ]}
      ]
    }
  }
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def transform(raw: dict, policies: list | None = None) -> dict:
    days: dict[str, list[dict]] = {}
    for forest_entry in raw.get("results", []):
        forest_name = forest_entry.get("forest") or ""
        for date_group in forest_entry.get("dates", []):
            use_dt = date_group.get("use_dt") or ""
            if not use_dt:
                continue
            rooms = [
                {
                    "name": room.get("name") or "",
                    "category": room.get("category") or "",
                    "capacity": room.get("capacity"),
                    "area": room.get("area"),
                    "price": room.get("price"),
                }
                for room in date_group.get("rooms", [])
            ]
            if not rooms:
                continue
            first_room = (date_group.get("rooms") or [{}])[0]
            days.setdefault(use_dt, []).append(
                {
                    "forest": forest_name,
                    # 숲나들e 예약 화면 URL(srchInsttId)에 그대로 쓰인다
                    "forest_id": first_room.get("forest_id") or "",
                    "region": first_room.get("region") or "",
                    "rooms": rooms,
                }
            )

    for entries in days.values():
        entries.sort(key=lambda e: e["forest"])

    return {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "range": raw.get("date_range") or {},
        "forests_scanned": raw.get("forests_scanned", 0),
        "fetch_failures": raw.get("fetch_failures", 0),
        "policies": policies or [],
        "days": dict(sorted(days.items())),
    }


def main() -> int:
    if len(sys.argv) not in (3, 4):
        print("usage: transform.py <raw.json> <vacancy.json> [policy.json]", file=sys.stderr)
        return 2
    with open(sys.argv[1], encoding="utf-8") as f:
        raw = json.load(f)
    policies = None
    if len(sys.argv) == 4:
        try:
            with open(sys.argv[3], encoding="utf-8") as f:
                policies = json.load(f)
        except (OSError, ValueError):
            pass  # 정책 파일이 없거나 깨져도 달력 본체는 배포한다
    out = transform(raw, policies)
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    total_rooms = sum(len(e["rooms"]) for entries in out["days"].values() for e in entries)
    print(
        f"vacancy.json 생성: {len(out['days'])}일 / "
        f"지점-날짜 {sum(len(v) for v in out['days'].values())}건 / 객실 {total_rooms}건 "
        f"(조회 실패 {out['fetch_failures']}건)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
