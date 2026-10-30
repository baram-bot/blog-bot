# -*- coding: utf-8 -*-
"""PAGES_DIR(기본 pages_nohu)/*.json 을 블로거 '페이지'로 만든다(이미 만든 건 data/<PAGES_DIR>.json 에 기록)."""
import glob, json, os, sys
import blog_bot as bb

ROOT = os.path.dirname(os.path.abspath(__file__))
PAGES_DIR = os.environ.get("PAGES_DIR", "pages_nohu")
STATE = os.path.join(ROOT, "data", f"{PAGES_DIR}.json")


def main():
    blog_id = os.environ["PAGES_BLOG_ID"]
    done = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}
    token = bb.google_access_token()
    for path in sorted(glob.glob(os.path.join(ROOT, PAGES_DIR, "*.json"))):
        name = os.path.basename(path)
        obj = json.load(open(path, encoding="utf-8"))
        body = {"kind": "blogger#page", "title": obj["title"], "content": obj["html"]}
        if name in done:
            url = f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/pages/{done[name]['id']}"
            res = bb.http_json(url, data=body, headers={"Authorization": f"Bearer {token}"}, method="PUT")
        else:
            url = f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/pages?isDraft=false"
            res = bb.http_json(url, data=body, headers={"Authorization": f"Bearer {token}"}, method="POST")
        done[name] = {"id": res.get("id"), "url": res.get("url"), "title": obj["title"]}
        print(f"[페이지] {obj['title']} → {res.get('url')}")
    json.dump(done, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
