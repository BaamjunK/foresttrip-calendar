#!/usr/bin/env python3
"""조회 스크립트의 raw JSON 을 달력 페이지가 읽는 vacancy.json 으로 변환한다.

사용법: python3 batch/transform.py data/raw.json docs/data/vacancy.json [data/policy.json]

policy.json(fetch_policy.py 산출물)이 주어지면 휴양림별 예약 오픈 규칙을
vacancy.json 의 "policies" 로 함께 실어 달력이 오픈일을 표시할 수 있게 한다.

raw 구조 (vendor/run_foresttrip_vacancy.py --json 출력):
  results[].forest / results[].dates[].use_dt / rooms[]

출력 구조 (schema v2) — 매일 커밋되는 파일이라 중복을 걷어낸 인덱스 참조형이다.
같은 지점·객실 정의가 날짜마다 되풀이되면(58일 × 3천여 객실) 5MB 를 넘고
저장소가 1년에 GB 단위로 자란다. 지점·객실·유형을 마스터로 빼고 날짜별로는
인덱스와 요금만 남겨 5배 이상 줄인다.

  {
    "v": 2,
    "generated_at": "2026-08-04T08:00:00+09:00",
    "range": {"from": "20260804", "to": "20260930"},
    "forests_scanned": 186,
    "fetch_failures": 0,
    "policies": [{"name": "...", "sigungu": "...", "type": "공립", "rule": "...", "open_day": 1}],
    "categories": ["숲속의집", "연립동", ...],
    "forests":  [["[공립](강릉시)임해자연휴양림", "ID02030100", "강원"], ...],
    "rooms":    [["하늘동 201호", 1, 5, 36], ...],   # 이름, 유형 idx, 정원, 면적(㎡)
    "days": {
      "20260804": [[3, [[128, 130000], [129, 0]]], ...]   # 지점 idx, [[객실 idx, 요금]]
    }
  }

요금 0 은 "가격 미확인"을 뜻한다(실제 요금 최저가 2만원이라 충돌하지 않는다).
정원·면적은 값이 없으면 0.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
SCHEMA_VERSION = 2


def parse_area(value) -> int:
    """'39㎡' → 39. 숫자로 만들 수 없으면 0."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    m = re.search(r"\d+", str(value))
    return int(m.group()) if m else 0


def parse_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def transform(
    raw: dict, policies: list | None = None, directory: list | None = None
) -> dict:
    categories: list[str] = []
    cat_idx: dict[str, int] = {}
    forests: list[list] = []
    forest_idx: dict[str, int] = {}
    rooms: list[list] = []
    room_idx: dict[tuple, int] = {}
    days: dict[str, list] = {}

    def intern_category(name: str) -> int:
        if name not in cat_idx:
            cat_idx[name] = len(categories)
            categories.append(name)
        return cat_idx[name]

    def intern_forest(name: str, forest_id: str, region: str) -> int:
        key = forest_id or name
        if key not in forest_idx:
            forest_idx[key] = len(forests)
            forests.append([name, forest_id, region])
        return forest_idx[key]

    def intern_room(room: dict) -> int:
        key = (
            room.get("name") or "",
            room.get("category") or "",
            parse_int(room.get("capacity")),
            parse_area(room.get("area")),
        )
        if key not in room_idx:
            room_idx[key] = len(rooms)
            rooms.append([key[0], intern_category(key[1]), key[2], key[3]])
        return room_idx[key]

    for forest_entry in raw.get("results", []):
        forest_name = forest_entry.get("forest") or ""
        for date_group in forest_entry.get("dates", []):
            use_dt = date_group.get("use_dt") or ""
            raw_rooms = date_group.get("rooms") or []
            if not use_dt or not raw_rooms:
                continue
            first = raw_rooms[0]
            fi = intern_forest(
                forest_name, first.get("forest_id") or "", first.get("region") or ""
            )
            slots = [[intern_room(r), parse_int(r.get("price"))] for r in raw_rooms]
            days.setdefault(use_dt, []).append([fi, slots])

    # 상세 팝업이 지점명 순으로 보이도록 미리 정렬해 둔다(렌더러는 그대로 그린다)
    for entries in days.values():
        entries.sort(key=lambda e: forests[e[0]][0])

    return {
        "v": SCHEMA_VERSION,
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "range": raw.get("date_range") or {},
        "forests_scanned": raw.get("forests_scanned", 0),
        "fetch_failures": raw.get("fetch_failures", 0),
        "policies": policies or [],
        # 빈자리 유무와 무관한 전 지점 목록 [이름, 지점ID, 시·도].
        # 예약 오픈 목록에서 빈자리 없는 휴양림도 지점 페이지로 링크하는 데 쓴다.
        "directory": directory or [],
        "categories": categories,
        "forests": forests,
        "rooms": rooms,
        "days": dict(sorted(days.items())),
    }


def load_optional(path: str | None):
    """없거나 깨진 부가 파일은 건너뛴다 — 달력 본체는 그대로 배포한다."""
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def main() -> int:
    if len(sys.argv) not in (3, 4, 5):
        print(
            "usage: transform.py <raw.json> <vacancy.json> [policy.json] [directory.json]",
            file=sys.stderr,
        )
        return 2
    with open(sys.argv[1], encoding="utf-8") as f:
        raw = json.load(f)
    policies = load_optional(sys.argv[3] if len(sys.argv) > 3 else None)
    directory = load_optional(sys.argv[4] if len(sys.argv) > 4 else None)
    out = transform(raw, policies, directory)
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    groups = sum(len(v) for v in out["days"].values())
    slots = sum(len(g[1]) for v in out["days"].values() for g in v)
    priced = sum(1 for v in out["days"].values() for g in v for s in g[1] if s[1])
    import os

    size_kb = os.path.getsize(sys.argv[2]) // 1024
    print(
        f"vacancy.json 생성: {len(out['days'])}일 / 지점-날짜 {groups}건 / "
        f"객실 {slots}건(요금 확인 {priced}건) · "
        f"마스터 지점 {len(out['forests'])}·객실 {len(out['rooms'])}·유형 {len(out['categories'])} · "
        f"{size_kb}KB (조회 실패 {out['fetch_failures']}건)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
