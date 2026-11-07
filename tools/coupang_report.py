# -*- coding: utf-8 -*-
"""쿠팡 파트너스 실적(클릭·주문·수익) 일별 합계. 읽기 전용."""
import os, sys, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shorts"))
import coupang_api as c
end = dt.date.today(); start = end - dt.timedelta(days=int(os.environ.get("DAYS", "14")))
q = f"startDate={start:%Y%m%d}&endDate={end:%Y%m%d}"
for kind in ("clicks", "orders", "commission"):
    try:
        data = c._call("GET", f"{c.BASE}/reports/{kind}?{q}") or []
        tot = {}
        for r in data:
            for k, v in r.items():
                if isinstance(v, (int, float)) and k not in ("date",):
                    tot[k] = tot.get(k, 0) + v
        print(kind, "합계", tot)
        for r in data[-7:]:
            print("  ", r)
    except Exception as e:
        print(kind, "실패", e)
