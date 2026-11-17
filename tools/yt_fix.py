# -*- coding: utf-8 -*-
"""영상 손보기(삭제 없음): PRIVATE_IDS 는 비공개로, RETITLE_ID 는 제목을 NEW_TITLE 로 바꾼다."""
import os
import requests

API = "https://www.googleapis.com/youtube/v3"
tok = requests.post("https://oauth2.googleapis.com/token", data={
    "client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
    "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"], "grant_type": "refresh_token"}, timeout=30).json()["access_token"]
h = {"Authorization": "Bearer " + tok}


def get(vid, part):
    items = requests.get(f"{API}/videos", params={"part": part, "id": vid}, headers=h, timeout=30).json().get("items", [])
    return items[0] if items else None


for vid in [x.strip() for x in os.environ.get("PRIVATE_IDS", "").split(",") if x.strip()]:
    v = get(vid, "status")
    if not v:
        print(f"[없음] {vid}")
        continue
    st = v["status"]
    body = {"id": vid, "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": st.get("selfDeclaredMadeForKids", False)}}
    r = requests.put(f"{API}/videos", params={"part": "status"}, headers=h, json=body, timeout=30)
    print(f"[비공개] {vid}: {'완료' if r.ok else r.status_code} {'' if r.ok else r.text[:200]}")

rid, new = os.environ.get("RETITLE_ID", "").strip(), os.environ.get("NEW_TITLE", "").strip()
if rid and new:
    v = get(rid, "snippet")
    if v:
        sn = v["snippet"]
        body = {"id": rid, "snippet": {"title": new[:100], "description": sn.get("description", ""),
                                       "tags": sn.get("tags", []), "categoryId": sn.get("categoryId", "22"),
                                       "defaultLanguage": sn.get("defaultLanguage", "ko")}}
        r = requests.put(f"{API}/videos", params={"part": "snippet"}, headers=h, json=body, timeout=30)
        print(f"[제목] {sn['title']} → {new}: {'완료' if r.ok else r.status_code} {'' if r.ok else r.text[:200]}")
