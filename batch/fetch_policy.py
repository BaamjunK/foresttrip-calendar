#!/usr/bin/env python3
"""숲나들e 예약 정책 페이지에서 휴양림별 예약 오픈 규칙을 수집한다.

사용법: fetch_policy.py <policy.json>

https://www.foresttrip.go.kr/pot/cc/bb/selectFripRsrvtPolcyView.do (공개, 로그인 불필요)
의 dayListTable 을 파싱해 휴양림별 오픈 규칙을 추출한다.
- 공립/사립: "매월 1일 09시 오픈" 같은 명시 텍스트 → open_day(매월 N일)도 추출
- 국립: 선착순 "6주 (수요일)" 방식이라 고정 일자가 없음 (월별예약조회 대상도 아님)
페이지 구조가 바뀌어 파싱이 실패하면 종료 코드 1 — deploy.sh 는 기존 파일을 유지한다.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request

POLICY_URL = (
    "https://www.foresttrip.go.kr/pot/cc/bb/selectFripRsrvtPolcyView.do"
    "?hmpgId=FRIP&menuId=002002"
)
TYPE_LABELS = ("국립", "공립", "사립")


def strip_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", text).strip()


def parse(html: str) -> list[dict]:
    m = re.search(r'<table class="tbl" id="dayListTable">(.*?)</table>', html, re.S)
    if not m:
        raise ValueError("dayListTable 을 찾지 못함")
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S)

    policies: list[dict] = []
    current_type = ""
    current_region = ""
    for row in rows:
        cells = [strip_tags(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if not cells:
            continue
        if cells[0] in TYPE_LABELS:
            current_type = cells[0]
        # 셀 위치는 rowspan(시·도/구분 생략) 때문에 행마다 다르다. 대신 운영현황
        # 3칸(객실/야영장/대기)이 O·X 로만 채워지는 걸 기준점으로 삼아 역산한다:
        #   [... 시·군·구, 휴양림명, O, X, O, 선착순, 추첨, 우선예약 ...]
        # "휴양림"으로 끝나는 셀을 찾는 방식은 "공주산림휴양마을",
        # "금산산림문화타운" 처럼 다르게 끝나는 이름을 놓친다.
        ox_idx = next(
            (
                i
                for i in range(1, len(cells) - 2)
                if all(cells[i + j] in ("O", "X") for j in range(3))
            ),
            None,
        )
        if ox_idx is None or ox_idx < 1:
            continue  # 헤더 행 등
        name = cells[ox_idx - 1]
        prev = cells[ox_idx - 2].strip() if ox_idx >= 2 else ""
        sigungu = prev if re.search(r"(시|군|구)$", prev) else ""
        if not name or name.replace(" ", "") in ("휴양림", "운영현황"):
            continue
        # 시·도 셀은 rowspan 으로 생략되는 행이 많다. 나타난 행에서만 갱신하고
        # 이후 행은 직전 값을 잇는다(구분 셀과 같은 방식).
        # 시·군·구 앞칸이 시·도이며, "서울인천경기"처럼 묶여 있다.
        if ox_idx >= 3:
            cand = cells[ox_idx - 3].strip()
            if cand and cand not in TYPE_LABELS and not re.search(r"(시|군|구)$", cand):
                current_region = cand
        # 오픈 규칙 셀: "오픈"이 들어간 셀 (예: "매월 1일 09시 오픈")
        rule = next((c for c in cells if "오픈" in c), "")
        rule = re.sub(r"^O\s+", "", rule)  # 국립 행은 운영여부 O 와 붙어 나옴
        # 국립의 선착순 주기는 표 헤더("6주 (수요일)")에만 있어 행 텍스트에 보충
        if current_type == "국립" and rule and "매월" not in rule:
            rule = "6주 전 수요일 " + rule
        open_day = None
        day_match = re.search(r"매월\s*(\d{1,2})일", rule)
        if day_match:
            open_day = int(day_match.group(1))
        policies.append(
            {
                # name 은 지점명 매칭용이라 공백을 지운다. 다만 숲나들e 통합검색은
                # 띄어쓰기를 그대로 지켜야 찾아진다("수락산 동막골 자연휴양림" 1건 /
                # 붙여 쓰면 0건). 표시·검색용 원본을 label 로 따로 남긴다.
                "name": re.sub(r"\s+", "", name),
                "label": re.sub(r"\s+", " ", name).strip(),
                "sigungu": sigungu,
                "region": current_region,
                "type": current_type,
                "rule": rule,
                "open_day": open_day,
            }
        )
    return policies


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: fetch_policy.py <policy.json>", file=sys.stderr)
        return 2
    request = urllib.request.Request(
        POLICY_URL, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", "replace")
    policies = parse(html)
    if len(policies) < 50:  # 정상이면 180행 안팎 — 급감은 구조 변경 신호
        print(f"파싱 결과가 비정상적으로 적음: {len(policies)}건", file=sys.stderr)
        return 1
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump(policies, f, ensure_ascii=False)
    with_day = sum(1 for p in policies if p["open_day"])
    print(f"예약 오픈 규칙 {len(policies)}건 수집 (매월 고정일 {with_day}건)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
