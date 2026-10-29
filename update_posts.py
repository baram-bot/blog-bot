# -*- coding: utf-8 -*-
"""이미 발행된 글을 posts/ 의 최신 내용으로 다시 고쳐 올린다.

data/update_queue.txt 에 posts/ 파일 이름을 한 줄에 하나씩 적고 push 하면
GitHub Actions 가 이 스크립트를 실행한다. 처리한 줄은 큐에서 지운다.
"""
import json
import os
import sys

import blog_bot as bb

ROOT = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(ROOT, "data", "update_queue.txt")


def main():
    if not os.path.exists(QUEUE):
        print("수정할 글 없음")
        return 0
    names = [l.strip() for l in open(QUEUE, encoding="utf-8") if l.strip() and not l.startswith("#")]
    state = bb.load_state()
    ids = {p.get("file"): p.get("post_id") for p in state["posted"] if p.get("file") and p.get("post_id")}
    blog_id = bb.env("BLOGGER_BLOG_ID")
    token = bb.google_access_token()
    failed = []
    for name in names:
        post_id = ids.get(name)
        if not post_id:
            print(f"[건너뜀] {name}: 아직 발행 안 됨(발행될 때 새 내용으로 올라감)")
            continue
        obj = json.load(open(os.path.join(bb.POSTS_DIR, name), encoding="utf-8"))
        article = {
            "title": str(obj["title"]).strip(),
            "html": bb.sanitize_html(obj["html"]),
            "labels": [str(x).strip() for x in obj.get("labels", []) if str(x).strip()][:6],
        }
        content = bb.assemble(article, None, None, notice=str(obj.get("notice", "")).strip() or None)
        url = f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts/{post_id}"
        try:
            res = bb.http_json(url, data={"title": article["title"], "content": content,
                                          "labels": article["labels"]},
                               headers={"Authorization": f"Bearer {token}"}, method="PATCH")
            print(f"[수정 완료] {name} → {res.get('url', '')}")
        except Exception as e:  # noqa: BLE001
            print(f"[수정 실패] {name}: {str(e)[:300]}")
            failed.append(name)
    with open(QUEUE, "w", encoding="utf-8") as f:
        f.write("# 다시 고쳐 올릴 posts/ 파일 이름 (한 줄에 하나)\n" + "".join(n + "\n" for n in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
