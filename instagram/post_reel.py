# -*- coding: utf-8 -*-
"""시니어 사연 쇼츠 → 인스타 릴스 (하루 1편).
shorts 워크플로가 영상을 만든 뒤 실행된다. 오늘(한국 날짜) 아직 릴스를 안 올렸고,
방금 만든 쇼츠가 '사연'이면 그 영상을 저장소에 올려 공개 주소를 만들고 릴스로 게시한다.
환경변수: IG_ACCESS_TOKEN, IG_USER_ID"""
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
IG_ID = os.environ.get("IG_USER_ID", "").strip()
REPO = os.environ.get("GITHUB_REPOSITORY", "baram-bot/blog-bot")
H = "https://graph.facebook.com/v21.0"
LOG = os.path.join(ROOT, "data", "ig_reels.json")
FOLLOW = "🙏 매일 가슴 찡한 사연, 계속 보시려면 팔로우 부탁드려요! @gureum_happy_story"


def call(method, path, **p):
    p["access_token"] = TOKEN
    r = requests.request(method, f"{H}/{path}", params=p if method == "GET" else None,
                         data=p if method == "POST" else None, timeout=60)
    js = r.json() if r.content else {}
    if r.status_code >= 400 or "error" in js:
        raise RuntimeError((js.get("error") or {}).get("message") or r.text[:300])
    return js


def git(*a):
    subprocess.run(["git", *a], cwd=ROOT, check=True)


def caption(s):
    lines = [l for l in (s.get("description") or "").split("\n") if "http" not in l and "구독" not in l]
    tags = [t for t in (s.get("tags") or []) if t.startswith("#") and t != "#shorts"][:8] + ["#릴스", "#사연"]
    tags = list(dict.fromkeys(tags))
    body = "\n".join(lines).strip()
    return (f"{body}\n\n👉 뒷이야기 전체는 유튜브 '바람따라구름따라'에서 들으실 수 있어요\n\n{FOLLOW}\n\n" + " ".join(tags))[:2100]


def main():
    if not TOKEN or not IG_ID:
        print("[릴스] 인스타 토큰 없음 — 건너뜀")
        return 0
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y%m%d")
    log = json.load(open(LOG, encoding="utf-8")) if os.path.exists(LOG) else {"posted": []}
    if any(x.get("date") == today for x in log["posted"]):
        print("[릴스] 오늘은 이미 올림")
        return 0
    cands = []
    for f in sorted(glob.glob(os.path.join(ROOT, "shorts", "done", today + "-*.json"))):
        name = os.path.splitext(os.path.basename(f))[0]
        s = json.load(open(f, encoding="utf-8"))
        mp4 = os.path.join(ROOT, "shorts", "_out", name + ".mp4")
        if s.get("kind") == "사연" and s.get("yt_id") and os.path.exists(mp4) and "시험" not in s.get("title", ""):
            cands.append((name, s, mp4))
    if not cands:
        print("[릴스] 오늘 만든 사연 쇼츠 없음")
        return 0
    name, s, mp4 = cands[0]
    rel = f"instagram/media/reels/{name}.mp4"
    os.makedirs(os.path.dirname(os.path.join(ROOT, rel)), exist_ok=True)
    shutil.copy(mp4, os.path.join(ROOT, rel))
    git("config", "user.name", "shorts-bot")
    git("config", "user.email", "shorts-bot@users.noreply.github.com")
    git("add", rel)
    git("commit", "-qm", f"인스타 릴스 영상 {name} [skip ci]")
    for _ in range(3):
        try:
            git("pull", "--rebase", "-q", "origin", "main")
            git("push", "-q", "origin", "HEAD:main")
            break
        except subprocess.CalledProcessError:
            time.sleep(5)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    url = f"https://raw.githubusercontent.com/{REPO}/{sha}/{rel}"
    time.sleep(10)
    cap = caption(s)
    cid = call("POST", f"{IG_ID}/media", media_type="REELS", video_url=url, caption=cap, share_to_feed="true")["id"]
    end = time.time() + 600
    while time.time() < end:
        st = call("GET", cid, fields="status_code").get("status_code")
        if st == "FINISHED":
            break
        if st in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"컨테이너 {st}")
        time.sleep(8)
    mid = None
    for i in range(4):
        try:
            mid = call("POST", f"{IG_ID}/media_publish", creation_id=cid)["id"]
            break
        except RuntimeError as e:
            print(f"[릴스] 게시 재시도 {i + 1}: {e}")
            time.sleep(20)
            # 이미 올라갔는지 확인(오류가 나도 실제로는 올라가는 경우가 있음)
            try:
                for m in call("GET", f"{IG_ID}/media", fields="id,caption", limit="3").get("data", []):
                    if (m.get("caption") or "")[:60] == cap[:60]:
                        mid = m["id"]
            except RuntimeError:
                pass
            if mid:
                break
    if not mid:
        raise RuntimeError("릴스 게시 실패")
    link = ""
    try:
        link = call("GET", mid, fields="permalink").get("permalink", "")
    except RuntimeError:
        pass
    print(f"[릴스] 게시 완료: {s.get('title')} {link}")
    log["posted"].append({"date": today, "file": name, "title": s.get("title"), "ig_media_id": mid, "permalink": link})
    json.dump(log, open(LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    git("add", LOG)
    git("commit", "-qm", "인스타 릴스 기록 [skip ci]")
    for _ in range(3):
        try:
            git("pull", "--rebase", "-q", "origin", "main")
            git("push", "-q", "origin", "HEAD:main")
            break
        except subprocess.CalledProcessError:
            time.sleep(5)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 — 릴스 실패가 쇼츠 작업을 실패로 만들지 않게
        print(f"[릴스] 실패: {e}")
        sys.exit(0)
