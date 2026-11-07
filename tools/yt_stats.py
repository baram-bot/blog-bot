# -*- coding: utf-8 -*-
"""채널 최근 영상 조회수 표 (게시 시각·길이·조회수·좋아요·댓글). 읽기 전용."""
import os, re, sys
OUT = os.environ.get("OUT")
_lines = []
_p = print
def print(*a, **k):
    _lines.append(" ".join(str(x) for x in a)); _p(*a, **k)
import requests
API = "https://www.googleapis.com/youtube/v3"
r = requests.post("https://oauth2.googleapis.com/token", data={
    "client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
    "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"], "grant_type": "refresh_token"}, timeout=30)
h = {"Authorization": "Bearer " + r.json()["access_token"]}
ch = requests.get(f"{API}/channels", params={"part": "contentDetails,statistics,snippet", "mine": "true"}, headers=h).json()["items"][0]
print("채널", ch["snippet"]["title"], "구독", ch["statistics"].get("subscriberCount"), "총조회", ch["statistics"].get("viewCount"))
up = ch["contentDetails"]["relatedPlaylists"]["uploads"]
ids = [i["contentDetails"]["videoId"] for i in requests.get(f"{API}/playlistItems", params={"part": "contentDetails", "playlistId": up, "maxResults": 50}, headers=h).json()["items"]]
vs = requests.get(f"{API}/videos", params={"part": "snippet,statistics,contentDetails", "id": ",".join(ids)}, headers=h).json()["items"]
for v in vs:
    d = v["contentDetails"]["duration"]; m = re.findall(r"(\d+)([HMS])", d); sec = sum(int(n) * {"H": 3600, "M": 60, "S": 1}[u] for n, u in m)
    s = v["statistics"]
    print(f"{v['snippet']['publishedAt'][:16]}\t{sec}s\t{s.get('viewCount',0)}\t{s.get('likeCount',0)}\t{s.get('commentCount',0)}\t{v['id']}\t{v['snippet']['title'][:40]}")

if OUT:
    open(OUT, "w", encoding="utf-8").write("\n".join(_lines) + "\n")
