# -*- coding: utf-8 -*-
"""시니어 롱폼을 하나의 공개 재생목록으로 묶는다(이어 듣기 → 시청 시간↑).
없으면 만들고(ID는 data/playlist_senior.txt), 아직 안 들어간 롱폼(3분 넘는 영상)을 최신이 맨 앞에 오게 넣는다."""
import os, re, sys
import requests
API = "https://www.googleapis.com/youtube/v3"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDF = os.path.join(ROOT, "data", "playlist_senior.txt")
TITLE = "🎧 1시간 사연 오디오북 모음 | 틀어 두면 계속 이어져요"
DESC = ("잠들기 전, 일하면서 틀어 두기 좋은 1시간 사연 라디오 드라마 모음입니다.\n"
        "한 편이 끝나면 다음 사연이 자동으로 이어집니다.\n구독과 좋아요는 큰 힘이 됩니다 🙏\n"
        "※ 사연을 바탕으로 각색했으며 AI 이미지와 AI 음성을 사용했습니다.")

r = requests.post("https://oauth2.googleapis.com/token", data={
    "client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
    "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"], "grant_type": "refresh_token"}, timeout=30)
h = {"Authorization": "Bearer " + r.json()["access_token"]}

pid = open(IDF).read().strip() if os.path.exists(IDF) else ""
if not pid:  # 이미 같은 이름의 재생목록이 있으면 그것을 쓴다(중복 생성 방지)
    js = requests.get(f"{API}/playlists", params={"part": "snippet", "mine": "true", "maxResults": 50}, headers=h, timeout=30).json()
    for p_ in js.get("items", []):
        if p_["snippet"]["title"] == TITLE:
            pid = p_["id"]
            open(IDF, "w").write(pid + "\n")
            print("기존 재생목록 사용", pid)
            break
if not pid:
    js = requests.post(f"{API}/playlists", params={"part": "snippet,status"}, headers=h, json={
        "snippet": {"title": TITLE, "description": DESC, "defaultLanguage": "ko"},
        "status": {"privacyStatus": "public"}}, timeout=30).json()
    pid = js["id"]
    open(IDF, "w").write(pid + "\n")
    print("재생목록 만듦", pid)

have, page = set(), None
while True:
    q = {"part": "contentDetails", "playlistId": pid, "maxResults": 50}
    if page: q["pageToken"] = page
    js = requests.get(f"{API}/playlistItems", params=q, headers=h, timeout=30).json()
    have |= {i["contentDetails"]["videoId"] for i in js.get("items", [])}
    page = js.get("nextPageToken")
    if not page: break

ch = requests.get(f"{API}/channels", params={"part": "contentDetails", "mine": "true"}, headers=h).json()["items"][0]
up = ch["contentDetails"]["relatedPlaylists"]["uploads"]
ids, page = [], None
while True:
    q = {"part": "contentDetails", "playlistId": up, "maxResults": 50}
    if page: q["pageToken"] = page
    js = requests.get(f"{API}/playlistItems", params=q, headers=h).json()
    ids += [i["contentDetails"]["videoId"] for i in js.get("items", [])]
    page = js.get("nextPageToken")
    if not page: break
longs = []
for i in range(0, len(ids), 50):
    for v in requests.get(f"{API}/videos", params={"part": "snippet,contentDetails,status", "id": ",".join(ids[i:i+50])}, headers=h).json().get("items", []):
        m = re.findall(r"(\d+)([HMS])", v["contentDetails"]["duration"])
        sec = sum(int(n) * {"H": 3600, "M": 60, "S": 1}[u] for n, u in m)
        if sec > 180 and v["status"]["privacyStatus"] == "public" and "시험" not in v["snippet"]["title"]:
            longs.append((v["snippet"]["publishedAt"], v["id"], v["snippet"]["title"]))
added = 0
for _, vid, title in sorted(longs):  # 오래된 것부터 맨 앞에 넣어 → 최신이 맨 앞
    if vid in have: continue
    rr = requests.post(f"{API}/playlistItems", params={"part": "snippet"}, headers=h, json={
        "snippet": {"playlistId": pid, "position": 0, "resourceId": {"kind": "youtube#video", "videoId": vid}}}, timeout=30)
    print(("추가 " if rr.ok else f"실패 {rr.status_code} ") + title[:40])
    added += rr.ok
print(f"재생목록 {pid}: 새로 {added}편, 전체 {len(have) + added}편")
