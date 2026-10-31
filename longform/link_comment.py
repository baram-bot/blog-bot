"""쇼츠 → 롱폼 연결 댓글 봇 (컴퓨터 없이 클라우드에서 실행)

같은 사연의 쇼츠에 "30분 전체 이야기" 롱폼 링크를 댓글로 단다.
짝 찾기:
  1) longform/done/*.json 중 yt_id 와 from_short 가 있는 것 → from_short 쇼츠의 yt_id
  2) data/related_linked.txt 에 적힌 짝 ("쇼츠ID | 롱폼ID | 날짜")
이미 댓글을 단 쇼츠는 data/short_comments.txt 에 기록해 두고 다시 달지 않는다.
제목·설명·공개 상태는 건드리지 않는다. (댓글 고정은 유튜브 API가 막아 두어 직접 눌러야 함)
"""
import glob
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "shorts"))
import make_short as ms  # noqa: E402

DONE = os.path.join(HERE, "done")
LINKED = os.path.join(ROOT, "data", "related_linked.txt")
RECORD = os.path.join(ROOT, "data", "short_comments.txt")


def load(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def pairs():
    out = {}  # 쇼츠ID -> (롱폼ID, 롱폼 제목)
    for f in sorted(glob.glob(os.path.join(DONE, "*.json"))):
        d = load(f) or {}
        lid, fs = d.get("yt_id"), (d.get("from_short") or "").strip()
        if not lid or not fs or d.get("privacy") == "private":
            continue
        s = load(fs if os.path.isabs(fs) else os.path.join(ROOT, fs)) or {}
        if s.get("yt_id"):
            out[s["yt_id"]] = (lid, d.get("title", ""))
    if os.path.exists(LINKED):
        for line in open(LINKED, encoding="utf-8"):
            p = [x.strip() for x in line.split("|")]
            if len(p) >= 2 and p[0] and p[1] and p[0] not in out:
                out[p[0]] = (p[1], "")
    return out


def done_ids():
    if not os.path.exists(RECORD):
        return set()
    return {l.split("|")[0].strip() for l in open(RECORD, encoding="utf-8") if l.strip()}


def long_title(tok, lid):
    r = requests.get("https://www.googleapis.com/youtube/v3/videos",
                     params={"part": "snippet", "id": lid},
                     headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    items = r.json().get("items") or []
    return items[0]["snippet"]["title"] if items else ""


def comment(tok, sid, lid, title):
    text = ("📺 이 사연의 30분 전체 이야기는 여기서 보실 수 있어요 👇\n"
            f"https://youtu.be/{lid}")
    if title:
        text += f"\n\n「{title}」"
    r = requests.post("https://www.googleapis.com/youtube/v3/commentThreads",
                      params={"part": "snippet"},
                      headers={"Authorization": f"Bearer {tok}"},
                      json={"snippet": {"videoId": sid,
                                        "topLevelComment": {"snippet": {"textOriginal": text}}}},
                      timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"{r.status_code} {r.text[:300]}")


def main():
    try:
        return _main()
    except Exception as e:  # noqa: BLE001
        print(f"::error::{type(e).__name__}: {str(e)[:300]}")
        raise


def _main():
    todo = {s: v for s, v in pairs().items() if s not in done_ids()}
    if not todo:
        print("댓글 달 짝 없음")
        return 0
    tok = ms.yt_access_token()
    if not tok:
        print("유튜브 토큰 없음")
        print("::error::유튜브 토큰 없음")
        return 1
    try:
        sc = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": tok}, timeout=30).json().get("scope", "")
        print(f"::notice::유튜브 연결 권한: {sc}")
    except Exception:  # noqa: BLE001
        pass
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    ok, fail = [], []
    for sid, (lid, title) in todo.items():
        try:
            title = title or long_title(tok, lid)
            comment(tok, sid, lid, title)
            with open(RECORD, "a", encoding="utf-8") as fh:
                fh.write(f"{sid} | {lid} | {today}\n")
            ok.append(title or lid)
            print(f"[댓글] {sid} → {lid}")
        except Exception as e:  # noqa: BLE001
            fail.append(f"{sid}: {e}")
            print(f"[실패] {sid}: {e}")
            print(f"::error::댓글 실패 {sid}: {' '.join(str(e).split())[:400]}")
    msg = ""
    if ok:
        msg += "💬 쇼츠에 롱폼 링크 댓글을 달았어요\n" + "\n".join(f"· {t}" for t in ok)
        msg += "\n\n(원하시면 유튜브 앱에서 그 댓글을 '고정'해 주세요)"
    if fail:
        msg += ("\n\n" if msg else "") + "⚠️ 댓글 실패\n" + "\n".join(fail)[:600]
        if any("insufficient" in f.lower() or "403" in f for f in fail):
            msg += "\n\n유튜브 연결 권한에 '댓글 쓰기'가 없어서 생긴 문제예요. 연결을 다시 해야 해요."
    try:
        ms.tg("sendMessage", data={"chat_id": ms.chat_id(), "text": msg})
    except Exception as e:  # noqa: BLE001
        print(f"[알림] {e}")
    return 1 if fail and not ok else 0


if __name__ == "__main__":
    sys.exit(main())
