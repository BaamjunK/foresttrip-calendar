#!/usr/bin/env python3
"""국립·공립 휴양림의 카카오맵 평점을 모아 data/ratings.json 에 쌓는다.

사용법: fetch_ratings.py <directory.json> <out.json> [--max N] [--stale-days N]

왜 카카오맵인가
- 숲나들e 에는 평점이 없다(이용후기 게시판은 있지만 지점별 점수를 노출하지 않고,
  조회 API 의 편의시설 필드도 전부 비어서 온다).
- 카카오·네이버 공식 API 도 평점을 주지 않는다. 카카오맵 웹은 평점을 보여주지만
  SPA 라 렌더링이 필요해 Playwright 로 읽는다.

부하 관리
- 평점은 자주 바뀌지 않으므로 `--stale-days`(기본 14일)보다 오래된 것만 갱신하고,
  한 번에 `--max`(기본 40곳)까지만 본다. 매일 조금씩 돌려 전체를 최신으로 유지한다.
- 사립은 제외한다(요청 사항).

정확도
- 검색은 "시·군·구 + 휴양림명" 으로 하고, 첫 결과의 카테고리·이름을 확인해
  엉뚱한 장소를 잡으면 버린다(verified=false 로 남겨 다음에 다시 시도한다).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
SKIP_TYPES = ("사립",)
# 카카오맵 카테고리가 이 중 하나면 휴양림·야영장 계열로 본다
OK_CATEGORY = re.compile(r"(자연휴양림|휴양림|야영장|캠핑|공원|관광,명소|숙박)")


def bare(name: str) -> str:
    return re.sub(r"^\s*\([^)]*\)\s*", "", re.sub(r"^\s*\[[^\]]*\]\s*", "", name)).strip()


def sigungu(name: str) -> str:
    m = re.match(r"^\s*(?:\[[^\]]*\])?\s*\(([^)]*)\)", name)
    return m.group(1) if m else ""


def optype(name: str) -> str:
    m = re.match(r"^\s*\[([^\]]*)\]", name)
    return m.group(1) if m else ""


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    ap.add_argument("out")
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--stale-days", type=int, default=14)
    args = ap.parse_args()

    directory = json.loads(Path(args.directory).read_text(encoding="utf-8"))
    out_path = Path(args.out)
    store = {"generated_at": None, "places": {}}
    if out_path.exists():
        try:
            store = json.loads(out_path.read_text(encoding="utf-8"))
            store.setdefault("places", {})
        except Exception:
            pass

    now = datetime.now(KST)
    stale_before = now - timedelta(days=args.stale_days)

    def is_stale(fid: str) -> bool:
        rec = store["places"].get(fid)
        if not rec or not rec.get("fetched_at"):
            return True
        # 장소를 못 잡았거나 점수를 못 읽은 건 다음 회차에 다시 시도한다
        if not (rec.get("verified") and rec.get("score")):
            return True
        try:
            return datetime.fromisoformat(rec["fetched_at"]) < stale_before
        except Exception:
            return True

    targets = [
        (nm, fid) for nm, fid, _rg in directory
        if optype(nm) not in SKIP_TYPES and is_stale(fid)
    ]
    # 아직 한 번도 못 본 곳을 먼저 채운다
    targets.sort(key=lambda t: 0 if t[1] not in store["places"] else 1)
    targets = targets[: args.max]
    if not targets:
        print("갱신할 대상이 없습니다(모두 최신)")
        return 0

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright 가 필요합니다", file=sys.stderr)
        return 1

    ok = skipped = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            locale="ko-KR",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
        )
        page = ctx.new_page()
        for name, fid in targets:
            query = (sigungu(name) + " " + bare(name)).strip()
            rec = {"fetched_at": now.isoformat(timespec="seconds"), "query": query}
            try:
                page.goto("https://map.kakao.com/link/search/" + query,
                          wait_until="domcontentloaded", timeout=25000)
                try:
                    page.wait_for_selector("#info\\.search\\.place\\.list li", timeout=8000)
                except Exception:
                    pass
                page.wait_for_timeout(700)
                first = page.query_selector("#info\\.search\\.place\\.list > li")
                if first:
                    text = first.inner_text()
                    place = (text.splitlines() or [""])[0].strip()
                    cat = ""
                    el = first.query_selector(".subcategory, .cate")
                    if el:
                        cat = el.inner_text().strip()
                    m = re.search(r"([0-9]\.[0-9])\s*\n?\s*([0-9,]+)건", text)
                    rec["place"] = place
                    rec["category"] = cat
                    if m:
                        rec["score"] = float(m.group(1))
                        rec["reviews"] = int(m.group(2).replace(",", ""))
                    # 이름이 전혀 겹치지 않고 카테고리도 안 맞으면 신뢰하지 않는다
                    key = norm(bare(name)).replace("자연휴양림", "")[:3]
                    rec["verified"] = bool(
                        (key and key in norm(place)) or OK_CATEGORY.search(cat or "")
                    )
                else:
                    rec["verified"] = False
            except Exception as exc:
                rec["error"] = type(exc).__name__
                rec["verified"] = False
            store["places"][fid] = rec
            if rec.get("score") and rec.get("verified"):
                ok += 1
            else:
                skipped += 1
        browser.close()

    store["generated_at"] = now.isoformat(timespec="seconds")
    out_path.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    scored = sum(1 for r in store["places"].values() if r.get("score") and r.get("verified"))
    print(f"평점 수집: 이번 {len(targets)}곳(성공 {ok}·보류 {skipped}) · "
          f"누적 유효 {scored}곳 / 저장 {len(store['places'])}곳")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
