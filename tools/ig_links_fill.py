# -*- coding: utf-8 -*-
"""링크 모음 페이지에 영상 없이 '추천 꿀템'을 미리 채운다.
KEYWORDS="문풍지,가습기,..." TITLE="❄️ 겨울 필수 꿀템" → 검색어마다 쿠팡 상품 1개(5천~8만 원·로켓 우선)."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "instagram"))
import product_reel as pr  # noqa: E402

kws = [k.strip() for k in os.environ.get("KEYWORDS", "").split(",") if k.strip()]
used = {x["id"] for x in pr.load_log()["items"]}
items = []
for kw in kws:
    try:
        p = pr.pick([kw], used)
    except Exception as e:  # noqa: BLE001
        print(f"[추천] {kw} 실패: {e}")
        p = None
    if p:
        used.add(p["id"])
        items.append({"kw": kw, "id": p["id"], "name": p["name"], "link": p["link"], "image": p["image"], "price": p["price"]})
    time.sleep(1.5)  # 검색 API 한도 보호
json.dump({"title": os.environ.get("TITLE") or "추천 꿀템", "items": items}, open(pr.EXTRA, "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
pr.write_page(pr.load_log()["items"])
pr.push("링크 페이지 추천 꿀템 채우기 [skip ci]", pr.EXTRA, pr.PAGE)
print(f"[추천] {len(items)}개 채움: " + ", ".join(f"{x['kw']}→{x['name'][:20]}({x['price']})" for x in items))
