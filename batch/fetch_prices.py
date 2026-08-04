#!/usr/bin/env python3
"""raw.json 의 각 객실 행에 1박 요금(price)을 붙여 출력한다.

사용법: fetch_prices.py <raw.json> <out.json>

동작 원리
- 가격 API(/rep/or/innerFcfsRsrvtPssblGoodsDtlSmpl.do)는 객실(goodsId)×날짜 단위라
  전량 호출이 불가능하다(객실×날짜 수만 건).
- 응답의 listGoodsUnprc 가 요금 결정 키를 알려준다: (객실, 시즌 ssnTpcd, 주중/주말 dtTpcd).
  같은 조합이면 날짜가 달라도 요금이 같으므로 조합별 1회만 호출한다.
- 캐시(data/price_cache.json, git 제외):
    prices:      "goodsId|ssn|dt" -> 1박 요금(원)
    date_bucket: "insttId|YYYYMMDD" -> "ssn|dt"  (그 지점에서 그 날짜의 시즌/요일 구분)
- 호출 상한(기본 1500, env PRICE_CALL_CAP)으로 일일 부하를 제한한다.
  상한에 걸린 객실은 price=null 로 남고 다음 배치가 이어서 채운다.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import threading
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor"))
import run_foresttrip_vacancy as v  # noqa: E402

DETAIL_URL = "https://www.foresttrip.go.kr/rep/or/innerFcfsRsrvtPssblGoodsDtlSmpl.do"
CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "price_cache.json"
CALL_CAP = int(os.getenv("PRICE_CALL_CAP", "1500"))
CONCURRENCY = 3


def get_session() -> "v.Session":
    cache_path = Path("~/.cache/k-skill/foresttrip-vacancy/session.json").expanduser()
    cached = v.load_session_cache(cache_path)
    # 구버전 캐시에는 sidos 가 없을 수 있으나 가격 조회에는 불필요하므로 그대로 쓴다
    if cached is not None:
        return cached
    session = v.bootstrap_session(
        forest_id=v.require_env("KSKILL_FORESTTRIP_ID"),
        forest_pw=v.require_env("KSKILL_FORESTTRIP_PASSWORD"),
    )
    v.save_session_cache(cache_path, session)
    return session


def fetch_detail(session, instt_id: str, goods_id: str, use_dt: str):
    """성공 시 (bucket "ssn|dt", price) 반환, 실패 시 None."""
    payload = {
        "srchInsttId": instt_id,
        "srchGoodsId": goods_id,
        "srchRsrvtBgDt": use_dt,
        "srchSthngCnt": "1",
    }
    headers = v.build_headers(session)
    headers["X-Ajax-call"] = "true"
    request = urllib.request.Request(
        DETAIL_URL, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    rows = data.get("listGoodsUnprc") if isinstance(data, dict) else None
    if not rows:
        return None
    first = rows[0]
    ssn, dt, price = first.get("ssnTpcd"), first.get("dtTpcd"), first.get("goodsUnprc")
    if not ssn or not dt or price is None:
        return None
    return f"{ssn}|{dt}", int(price)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: fetch_prices.py <raw.json> <out.json>", file=sys.stderr)
        return 2
    raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

    cache = {"prices": {}, "date_bucket": {}}
    if CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    prices: dict[str, int] = cache.setdefault("prices", {})
    date_bucket: dict[str, str] = cache.setdefault("date_bucket", {})

    # 모든 객실 행을 (지점, 날짜) 그룹으로 평탄화
    rooms: list[dict] = []
    for forest_entry in raw.get("results", []):
        for date_group in forest_entry.get("dates", []):
            rooms.extend(date_group.get("rooms", []))

    lock = threading.Lock()
    calls_left = CALL_CAP
    stats = {"calls": 0, "errors": 0}

    def learn(room: dict) -> None:
        nonlocal calls_left
        with lock:
            if calls_left <= 0:
                return
            calls_left -= 1
            stats["calls"] += 1
        result = fetch_detail(session, room["forest_id"], room["goods_id"], room["use_dt"])
        with lock:
            if result is None:
                stats["errors"] += 1
                return
            bucket, price = result
            date_bucket[f"{room['forest_id']}|{room['use_dt']}"] = bucket
            prices[f"{room['goods_id']}|{bucket}"] = price

    def assign() -> list[dict]:
        """캐시로 채울 수 있는 가격을 채우고, 아직 모르는 객실 행을 돌려준다."""
        unknown = []
        for room in rooms:
            if not room.get("goods_id"):
                room["price"] = None
                continue
            bucket = date_bucket.get(f"{room['forest_id']}|{room['use_dt']}")
            price = prices.get(f"{room['goods_id']}|{bucket}") if bucket else None
            room["price"] = price
            if price is None:
                unknown.append(room)
        return unknown

    session = get_session()

    # 1차: 버킷 미상 (지점|날짜) 그룹마다 대표 1건 호출 → 버킷 + 그 객실 요금 학습
    unknown = assign()
    probe_by_group: dict[str, dict] = {}
    for room in sorted(unknown, key=lambda r: r["use_dt"]):  # 가까운 날짜 우선
        key = f"{room['forest_id']}|{room['use_dt']}"
        if key not in date_bucket:
            probe_by_group.setdefault(key, room)
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        list(pool.map(learn, probe_by_group.values()))

    # 2차: 버킷은 알지만 (객실|버킷) 요금 미상 → 조합당 1건만 호출
    unknown = assign()
    seen_pairs: set[str] = set()
    todo = []
    for room in sorted(unknown, key=lambda r: r["use_dt"]):
        bucket = date_bucket.get(f"{room['forest_id']}|{room['use_dt']}")
        if bucket is None:
            continue  # 1차 상한 초과분 — 다음 배치에서
        pair = f"{room['goods_id']}|{bucket}"
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        todo.append(room)
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        list(pool.map(learn, todo))

    remaining = len(assign())
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    Path(sys.argv[2]).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    priced = sum(1 for r in rooms if r.get("price") is not None)
    print(
        f"가격 부여: {priced}/{len(rooms)}건 (미확인 {remaining}건) · "
        f"API 호출 {stats['calls']}건(실패 {stats['errors']}) · "
        f"캐시 조합 {len(prices)}개"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
