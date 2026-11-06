# -*- coding: utf-8 -*-
"""쿠팡 파트너스 Open API — 영상 주제 키워드로 상품을 검색해 파트너스 단축 링크를 만든다.
키(깃허브 비밀값 COUPANG_ACCESS_KEY / COUPANG_SECRET_KEY)가 없거나 실패하면 None → 기존 링크 목록을 쓴다.
검색 API는 호출 한도가 빡빡하므로 영상 1편에 최대 2번(키워드 2개)만 부른다."""
import hashlib
import hmac
import json
import os
import time
import urllib.parse

import requests

DOMAIN = "https://api-gateway.coupang.com"
BASE = "/v2/providers/affiliate_open_api/apis/openapi/v1"
AK = os.environ.get("COUPANG_ACCESS_KEY", "").strip()
SK = os.environ.get("COUPANG_SECRET_KEY", "").strip()
SUB = os.environ.get("COUPANG_SUB_ID", "youtube")
# 영상과 함께 걸면 안 되는 상품(의약품·건강기능식품·금융·성인 등)
BLOCK = ("의약", "영양제", "건강기능", "비타민", "유산균", "홍삼", "다이어트", "보험", "대출", "성인", "콘돔", "담배", "술", "소주", "맥주", "와인")


def enabled():
    return bool(AK and SK)


def _auth(method, url_path):
    path, _, query = url_path.partition("?")
    t = time.gmtime()
    sd = time.strftime("%y%m%d", t) + "T" + time.strftime("%H%M%S", t) + "Z"
    sig = hmac.new(SK.encode(), (sd + method + path + query).encode(), hashlib.sha256).hexdigest()
    return f"CEA algorithm=HmacSHA256, access-key={AK}, signed-date={sd}, signature={sig}"


def _call(method, url_path, body=None):
    r = requests.request(method, DOMAIN + url_path, timeout=20,
                         headers={"Authorization": _auth(method, url_path),
                                  "Content-Type": "application/json;charset=UTF-8"},
                         data=json.dumps(body) if body else None)
    r.raise_for_status()
    js = r.json()
    if str(js.get("rCode", "0")) != "0":
        raise RuntimeError(js.get("rMessage"))
    return js.get("data")


def find(keywords):
    """키워드 순서대로 검색해 (링크, 상품명) 하나를 돌려준다. 로켓배송·검색 순위 우선."""
    if not enabled():
        return None
    for kw in [k.strip() for k in keywords if k and k.strip()][:2]:
        try:
            q = urllib.parse.urlencode({"keyword": kw, "limit": 10, "subId": SUB})
            items = (_call("GET", f"{BASE}/products/search?{q}") or {}).get("productData", [])
        except Exception as e:  # noqa: BLE001
            print(f"[쿠팡 API] '{kw}' 검색 실패: {e}")
            continue
        items = [p for p in items if p.get("productUrl") and not any(b in p.get("productName", "") for b in BLOCK)]
        if not items:
            print(f"[쿠팡 API] '{kw}' 맞는 상품 없음")
            continue
        items.sort(key=lambda p: (not p.get("isRocket"), p.get("rank", 99)))
        p = items[0]
        link = p["productUrl"]
        try:  # 설명란에 보기 좋은 짧은 링크로
            short = _call("POST", f"{BASE}/deeplink",
                          {"coupangUrls": [f"https://www.coupang.com/vp/products/{p['productId']}"], "subId": SUB}) or []
            link = (short[0] or {}).get("shortenUrl") or link
        except Exception as e:  # noqa: BLE001
            print(f"[쿠팡 API] 짧은 링크 실패(긴 링크 사용): {e}")
        name = p.get("productName", "").strip()[:60]
        print(f"[쿠팡 API] '{kw}' → {name} {link}")
        return link, name, kw
    return None
