# -*- coding: utf-8 -*-
"""애드센스 '가치가 별로 없는 콘텐츠' 대응 (경제노트 블로그).
1) 주제와 안 맞는 예전 여행 글을 '임시보관(초안)'으로 되돌린다(삭제 아님, 블로거에서 언제든 다시 게시 가능).
2) 블로그 페이지 목록과 본문 길이를 보여 준다.
MODE=list 면 목록만, MODE=revert 면 여행 글 초안 전환."""
import json, os, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import blog_bot as bb
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://www.googleapis.com/blogger/v3"
tok = bb.google_access_token(); blog = os.environ["BLOGGER_BLOG_ID"]
def call(method, url, body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None),
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")
mode = os.environ.get("MODE", "list")
pages = call("GET", f"{API}/blogs/{blog}/pages?fetchBodies=true").get("items", [])
for p in pages:
    import re
    txt = re.sub(r"<[^>]+>", "", p.get("content", ""))
    print(f"[페이지] {p['id']} {p['title']} 글자수 {len(txt)}")
posted = json.load(open(os.path.join(ROOT, "data", "posted.json"), encoding="utf-8"))["posted"]
travel = [p for p in posted if p["file"].startswith(("20261026-", "20261027-")) and p.get("post_id")]
for p in travel:
    print(f"[여행 글] {p['post_id']} {p['title'][:30]}")
    if mode == "revert":
        try:
            r = call("POST", f"{API}/blogs/{blog}/posts/{p['post_id']}/revert")
            print("   → 초안으로 전환", r.get("status"))
        except Exception as e:
            print("   ! 실패", e)

if mode == "pages":  # 내용이 거의 없는 페이지에 실제 글 내용을 채운다
    new = json.load(open(os.path.join(ROOT, "data", "adsense_pages.json"), encoding="utf-8"))
    for p in pages:
        if p["title"] == "분야별 글 모아보기":
            body = new["category"]
        elif p["title"] == "문의하기":
            if "답변 안내" in p.get("content", ""):
                continue
            body = new["contact_prefix"] + p.get("content", "")  # 기존 문의 양식은 그대로 아래에 둔다
        else:
            continue
        r = call("PATCH", f"{API}/blogs/{blog}/pages/{p['id']}", {"content": body})
        print("   → 페이지 보강", p["title"], len(r.get("content", "")))
