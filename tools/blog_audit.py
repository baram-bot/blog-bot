# -*- coding: utf-8 -*-
"""블로그 점검·정리(삭제 없음).
MODE=list   : 게시된 글 전체(날짜·글자 수·제목·라벨·ID)와 페이지 목록, 중복 제목 표시
MODE=revert : REVERT_IDS(쉼표) 글을 '임시보관'으로 되돌림 (나중에 다시 게시 가능)
BLOG=econ|nohu|kids"""
import html
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import blog_bot as bb  # noqa: E402

IDS = {"econ": os.environ.get("BLOGGER_BLOG_ID", ""), "nohu": "8885340922893837263", "kids": os.environ.get("KIDS_BLOG_ID", "")}
BLOG = os.environ.get("BLOG", "econ")
BID = IDS.get(BLOG) or ""
API = "https://www.googleapis.com/blogger/v3/blogs/"


def get(url, tok):
    return bb.http_json(url, headers={"Authorization": f"Bearer {tok}"})


def text_len(content):
    t = re.sub(r"<[^>]+>", " ", content or "")
    return len(re.sub(r"\s+", "", html.unescape(t)))


def main():
    tok = bb.google_access_token()
    bid = BID
    if not bid:
        blogs = get(API.replace("blogs/", "users/self/blogs"), tok).get("items", [])
        for b in blogs:
            print(f"[블로그] {b['id']} {b['name']} {b['url']}")
        name = {"kids": "육아"}.get(BLOG, "")
        bid = next((b["id"] for b in blogs if name and name in b["name"]), "")
    if os.environ.get("MODE", "list") == "revert":
        for pid in [x.strip() for x in os.environ.get("REVERT_IDS", "").split(",") if x.strip()]:
            try:
                r = bb.http_json(f"{API}{bid}/posts/{pid}/revert", data=b"", method="POST",
                                 headers={"Authorization": f"Bearer {tok}"})
                print(f"[임시보관] {pid} {r.get('title', '')} → {r.get('status', '')}")
            except Exception as e:  # noqa: BLE001
                print(f"[실패] {pid}: {e}")
        return 0
    posts, page = [], ""
    while True:
        q = {"maxResults": 50, "status": "live", "fetchBodies": "true", "fields": "nextPageToken,items(id,title,published,labels,content,url)"}
        if page:
            q["pageToken"] = page
        d = get(f"{API}{bid}/posts?{urllib.parse.urlencode(q)}", tok)
        posts += d.get("items", [])
        page = d.get("nextPageToken")
        if not page:
            break
    seen = {}
    for p in posts:
        key = re.sub(r"\s+", "", p["title"])
        seen.setdefault(key, []).append(p["id"])
    print(f"[글] 게시 {len(posts)}개")
    for p in sorted(posts, key=lambda x: x["published"]):
        dup = " [중복]" if len(seen[re.sub(r'\s+', '', p['title'])]) > 1 else ""
        print(f"{p['published'][:10]}\t{text_len(p.get('content'))}\t{p['id']}\t{','.join(p.get('labels', []))}\t{p['title']}{dup}")
    pages = get(f"{API}{bid}/pages?fetchBodies=true&status=live", tok).get("items", [])
    for pg in pages:
        print(f"[페이지] {pg['id']}\t{text_len(pg.get('content'))}\t{pg['title']}\t{pg.get('url', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
