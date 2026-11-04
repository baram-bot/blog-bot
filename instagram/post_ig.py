# -*- coding: utf-8 -*-
"""instagram/queue/*.json 카드뉴스 대본 → 카드 이미지 만들기 → 저장소에 올려 공개 주소 만들기 → 인스타 캐러셀 게시.
환경변수: IG_ACCESS_TOKEN(비밀값), IG_USER_ID, GITHUB_REPOSITORY
"""
import glob
import json
import os
import subprocess
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_cards  # noqa: E402
import make_reel  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Q = os.path.join(ROOT, "instagram", "queue")
DONE = os.path.join(ROOT, "instagram", "done")
MEDIA = os.path.join(ROOT, "instagram", "media")
TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
IG_ID = os.environ.get("IG_USER_ID", "").strip()
REPO = os.environ.get("GITHUB_REPOSITORY", "baram-bot/blog-bot")
HOSTS = ["https://graph.facebook.com/v21.0", "https://graph.instagram.com/v21.0"]


class IGError(Exception):
    pass


def call(method, path, host, **params):
    params["access_token"] = TOKEN
    r = requests.request(method, f"{host}/{path}", params=params if method == "GET" else None,
                         data=params if method == "POST" else None, timeout=60)
    js = r.json() if r.content else {}
    if r.status_code >= 400 or "error" in js:
        raise IGError((js.get("error") or {}).get("message") or r.text[:300])
    return js


def pick_host():
    last = ""
    for h in HOSTS:
        try:
            js = call("GET", IG_ID, h, fields="username,id")
            print(f"[인스타] 연결 확인: @{js.get('username')} ({h})")
            return h
        except IGError as e:
            last = str(e)
            print(f"[인스타] {h} 실패: {last}")
    raise IGError(f"인스타 연결 실패: {last}")


def wait_ready(host, cid, timeout=180):
    end = time.time() + timeout
    while time.time() < end:
        js = call("GET", cid, host, fields="status_code")
        st = js.get("status_code")
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise IGError(f"컨테이너 {st}")
        time.sleep(5)
    raise IGError("컨테이너 준비 시간 초과")


def git(*args):
    subprocess.run(["git", *args], cwd=ROOT, check=True)


FOLLOW = "🙏 더 좋은 정보, 계속 받아보시려면 팔로우 부탁드려요! @gureum_happy_story"


def with_follow(text):
    """캡션 끝(해시태그 앞)에 팔로우 부탁 한 줄을 넣는다."""
    text = (text or "").strip()
    if "팔로우" in text:
        return text[:2100]
    lines = text.split("\n")
    i = len(lines)
    while i > 0 and lines[i - 1].strip().startswith("#"):
        i -= 1
    head, tags = "\n".join(lines[:i]).rstrip(), "\n".join(lines[i:]).strip()
    out = (head + "\n\n" + FOLLOW + ("\n\n" + tags if tags else "")).strip()
    return out[:2100]


def publish_carousel(host, urls, caption):
    kids = []
    for u in urls:
        js = call("POST", f"{IG_ID}/media", host, image_url=u, is_carousel_item="true")
        kids.append(js["id"])
    for k in kids:
        wait_ready(host, k)
    js = call("POST", f"{IG_ID}/media", host, media_type="CAROUSEL", children=",".join(kids), caption=caption)
    cid = js["id"]
    wait_ready(host, cid)
    for attempt in range(4):
        try:
            return call("POST", f"{IG_ID}/media_publish", host, creation_id=cid)["id"]
        except IGError:
            if attempt == 3:
                raise
            time.sleep(10)


def publish_reel(host, url, caption):
    js = call("POST", f"{IG_ID}/media", host, media_type="REELS", video_url=url, caption=caption, share_to_feed="false")
    cid = js["id"]
    wait_ready(host, cid, timeout=600)
    for attempt in range(4):
        try:
            return call("POST", f"{IG_ID}/media_publish", host, creation_id=cid)["id"]
        except IGError:
            if attempt == 3:
                raise
            time.sleep(15)


def main():
    files = sorted(glob.glob(os.path.join(Q, "*.json")))
    if not files:
        print("올릴 카드뉴스 없음")
        return 0
    if not TOKEN or not IG_ID:
        print("IG_ACCESS_TOKEN / IG_USER_ID 없음")
        return 1
    host = pick_host()
    f = files[0]
    name = os.path.splitext(os.path.basename(f))[0]
    spec = json.load(open(f, encoding="utf-8"))
    outdir = os.path.join(MEDIA, name)
    paths = make_cards.build(spec, outdir)
    # 이미지를 공개 저장소에 올려 주소 만들기(인스타가 가져갈 수 있게)
    git("config", "user.name", "blog-bot")
    git("config", "user.email", "blog-bot@users.noreply.github.com")
    reel_path = None
    if spec.get("reel"):
        try:
            reel_path = os.path.join(outdir, "reel.mp4")
            sec = make_reel.build(spec, paths, os.path.join("/tmp", "reel_" + name), reel_path)
            print(f"[인스타] 릴스 영상 {sec:.0f}초")
        except Exception as e:  # noqa: BLE001
            print(f"[인스타] 릴스 만들기 실패(카드뉴스만 올림): {e}")
            reel_path = None
    git("add", outdir)
    git("commit", "-qm", f"인스타 카드 이미지 {name} [skip ci]")
    for i in range(3):
        try:
            git("pull", "--rebase", "-q", "origin", "main")
            git("push", "-q", "origin", "HEAD:main")
            break
        except subprocess.CalledProcessError:
            time.sleep(5)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    urls = [f"https://raw.githubusercontent.com/{REPO}/{sha}/instagram/media/{name}/{os.path.basename(p)}" for p in paths]
    time.sleep(10)
    caption = with_follow(spec.get("caption", ""))
    media_id = publish_carousel(host, urls, caption)
    link = ""
    try:
        link = call("GET", media_id, host, fields="permalink").get("permalink", "")
    except IGError:
        pass
    spec.update({"ig_media_id": media_id, "permalink": link, "posted_at": time.strftime("%Y-%m-%d %H:%M")})
    if reel_path:
        try:
            rurl = f"https://raw.githubusercontent.com/{REPO}/{sha}/instagram/media/{name}/reel.mp4"
            rcap = with_follow(spec["reel_caption"]) if spec.get("reel_caption") else caption
            rid = publish_reel(host, rurl, rcap)
            rlink = call("GET", rid, host, fields="permalink").get("permalink", "")
            spec.update({"reel_media_id": rid, "reel_permalink": rlink})
            link = (link + "\n🎬 릴스: " + rlink).strip()
            print(f"[인스타] 릴스 게시 완료: {rlink}")
        except Exception as e:  # noqa: BLE001
            print(f"[인스타] 릴스 게시 실패: {e}")
    os.makedirs(DONE, exist_ok=True)
    json.dump(spec, open(os.path.join(DONE, name + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.remove(f)
    print(f"[인스타] 게시 완료: {link or media_id}")
    tg = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if tg and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{tg}/sendMessage", timeout=20,
                          data={"chat_id": chat, "text": f"📸 인스타 카드뉴스를 올렸어요\n{spec['cover']['title']}\n{link}"})
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except IGError as e:
        print(f"[인스타] 오류: {e}")
        sys.exit(1)
