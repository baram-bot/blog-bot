# -*- coding: utf-8 -*-
"""쿠팡 파트너스 규정: 이미 올라간 영상 중 설명란에 쿠팡 링크가 있는 영상의 제목 앞에 [광고]를 붙인다.
토큰 권한(youtube 또는 youtube.force-ssl)이 없으면 무엇이 필요한지만 알려 주고 끝낸다.
DRY_RUN=1 이면 바꾸지 않고 목록만 출력.
MODE=remove 이면 반대로: 제목 앞 [광고]를 떼고, 대신 유튜브 '유료 광고 포함' 표시(paidProductPlacementDetails)를 켠다."""
import os
import re
import sys

import requests

API = "https://www.googleapis.com/youtube/v3"


def token():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": os.environ.get("YT_CLIENT_ID") or os.environ.get("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.environ.get("YT_CLIENT_SECRET") or os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"], "grant_type": "refresh_token"}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def main():
    name = os.environ.get("CH_NAME", "")
    if not os.environ.get("YOUTUBE_REFRESH_TOKEN"):
        print(f"[{name}] 토큰 없음")
        return 0
    tok = token()
    scope = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": tok}, timeout=30).json().get("scope", "")
    print(f"[{name}] 권한: {scope}")
    if not any(s in scope for s in ("auth/youtube ", "auth/youtube.force-ssl")) and not scope.endswith("auth/youtube"):
        print(f"[{name}] ⚠️ 제목 수정 권한 없음(업로드 전용 토큰). 스튜디오에서 직접 바꾸거나 권한을 다시 받아야 함")
        return 0
    h = {"Authorization": f"Bearer {tok}"}
    ch = requests.get(f"{API}/channels", params={"part": "contentDetails,snippet", "mine": "true"}, headers=h, timeout=30).json()
    up = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    print(f"[{name}] 채널: {ch['items'][0]['snippet']['title']}")
    ids, page = [], None
    while True:
        q = {"part": "contentDetails", "playlistId": up, "maxResults": 50}
        if page:
            q["pageToken"] = page
        js = requests.get(f"{API}/playlistItems", params=q, headers=h, timeout=30).json()
        ids += [it["contentDetails"]["videoId"] for it in js.get("items", [])]
        page = js.get("nextPageToken")
        if not page:
            break
    dry = os.environ.get("DRY_RUN") == "1"
    remove = os.environ.get("MODE") == "remove"
    strip = os.environ.get("MODE") == "strip"  # 쿠팡 링크·광고 문구·유료 광고 표시를 모두 지움
    n = 0
    for i in range(0, len(ids), 50):
        js = requests.get(f"{API}/videos", params={"part": "snippet,paidProductPlacementDetails", "id": ",".join(ids[i:i + 50])},
                          headers=h, timeout=30).json()
        for v in js.get("items", []):
            sn = v["snippet"]
            has_link = "link.coupang.com" in sn.get("description", "")
            if strip:
                paid = (v.get("paidProductPlacementDetails") or {}).get("hasPaidProductPlacement")
                old = sn.get("description", "")
                keep = [l for l in old.split("\n") if not re.search(r"coupang|쿠팡|\[광고\]|^\s*🛒", l)]
                desc = re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).strip()
                title = sn["title"][len("[광고]"):].strip() if sn["title"].startswith("[광고]") else sn["title"]
                if desc == old.strip() and title == sn["title"] and not paid:
                    continue
                print(f"  {v['id']}: {sn['title'][:30]} (설명 {len(old)}→{len(desc)}자, 표시 {'켬→끔' if paid else '없음'})")
                n += 1
                if dry:
                    continue
                if desc != old.strip() or title != sn["title"]:
                    body = {"id": v["id"], "snippet": {"title": title, "description": desc,
                                                        "categoryId": sn.get("categoryId", "22"), "tags": sn.get("tags", []),
                                                        "defaultLanguage": sn.get("defaultLanguage", "ko")}}
                    r = requests.put(f"{API}/videos", params={"part": "snippet"}, headers=h, json=body, timeout=30)
                    if not r.ok:
                        print(f"    ! 설명 실패 {r.status_code}: {r.text[:200]}")
                if paid:
                    r = requests.put(f"{API}/videos", params={"part": "paidProductPlacementDetails"}, headers=h,
                                     json={"id": v["id"], "paidProductPlacementDetails": {"hasPaidProductPlacement": False}},
                                     timeout=30)
                    if not r.ok:
                        print(f"    ! 표시 끄기 실패 {r.status_code}: {r.text[:200]}")
                continue
            if remove:
                titled = sn["title"].startswith("[광고]")
                paid = (v.get("paidProductPlacementDetails") or {}).get("hasPaidProductPlacement")
                if not titled and (paid or not has_link):
                    continue
                new = sn["title"][len("[광고]"):].strip() if titled else sn["title"]
            else:
                if not has_link or sn["title"].startswith("[광고]"):
                    continue
                new = ("[광고] " + sn["title"])[:100]
            print(f"  {v['id']}: {sn['title']} → {new}")
            n += 1
            if dry:
                continue
            if new != sn["title"]:
                body = {"id": v["id"], "snippet": {"title": new, "description": sn["description"],
                                                    "categoryId": sn.get("categoryId", "22"), "tags": sn.get("tags", []),
                                                    "defaultLanguage": sn.get("defaultLanguage", "ko")}}
                r = requests.put(f"{API}/videos", params={"part": "snippet"}, headers=h, json=body, timeout=30)
                if not r.ok:
                    print(f"    ! 제목 실패 {r.status_code}: {r.text[:200]}")
            if remove and has_link:
                r = requests.put(f"{API}/videos", params={"part": "paidProductPlacementDetails"}, headers=h,
                                 json={"id": v["id"], "paidProductPlacementDetails": {"hasPaidProductPlacement": True}},
                                 timeout=30)
                if not r.ok:
                    print(f"    ! 유료 광고 표시 실패 {r.status_code}: {r.text[:200]}")
    print(f"[{name}] 대상 {n}편")
    return 0


if __name__ == "__main__":
    sys.exit(main())
