# -*- coding: utf-8 -*-
"""인스타 최근 게시물 조회·도달 확인(읽기 전용)."""
import os, requests
T = os.environ["IG_ACCESS_TOKEN"].strip(); ID = os.environ["IG_USER_ID"].strip()
for H in ("https://graph.facebook.com/v21.0", "https://graph.instagram.com/v21.0"):
    a = requests.get(f"{H}/{ID}", params={"fields": "username,followers_count,media_count", "access_token": T}, timeout=30).json()
    if "error" not in a:
        break
print("계정", a)
ms = requests.get(f"{H}/{ID}/media", params={"fields": "id,timestamp,media_type,media_product_type,like_count,comments_count,caption", "limit": 20, "access_token": T}, timeout=30).json()
if "error" in ms:
    print("목록 오류", ms["error"].get("message"))
for m in ms.get("data", []):
    ins = requests.get(f"{H}/{m['id']}/insights", params={"metric": "reach,views,saved,shares", "access_token": T}, timeout=30).json()
    v = {d["name"]: d["values"][0]["value"] for d in ins.get("data", [])} if "data" in ins else ins.get("error", {}).get("message", "")[:80]
    print(m["timestamp"][:16], m.get("media_product_type"), "좋아요", m.get("like_count"), "댓글", m.get("comments_count"), v, (m.get("caption") or "")[:25].replace("\n", " "))
