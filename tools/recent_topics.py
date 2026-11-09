# -*- coding: utf-8 -*-
"""세 유튜브 채널 + 블로그의 최근 14일 제목을 한 파일로 모은다(주제 반복 방지용). data/recent_topics.txt"""
import datetime as dt, glob, json, os, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cut = (dt.datetime.utcnow() + dt.timedelta(hours=9) - dt.timedelta(days=14)).strftime("%Y%m%d")
out = ["# 최근 14일 동안 올라간 제목(자동 갱신). 아래와 같은 주제·같은 제도는 어느 채널이든 다시 쓰지 않는다.",
       "# 형식: 날짜 | 채널 | 제목"]
for d, name in (("shorts/done", "시니어 쇼츠"), ("shorts/queue", "시니어 쇼츠(대기)"), ("shorts_econ/done", "경제노트 쇼츠"),
                ("shorts_econ/queue", "경제노트 쇼츠(대기)"), ("shorts_kids/done", "육아 쇼츠"), ("longform/done", "시니어 롱폼"),
                ("posts", "경제노트 블로그"), ("posts_nohu", "노후 블로그")):
    for f in sorted(glob.glob(os.path.join(ROOT, d, "*.json"))):
        b = os.path.basename(f)[:8]
        if not b.isdigit() or b < cut:
            continue
        try:
            t = json.load(open(f, encoding="utf-8")).get("title", "")
        except Exception:
            continue
        t = re.sub(r"\s*#\S+", "", t).strip()
        if t and "시험" not in t:
            out.append(f"{b[4:6]}/{b[6:]} | {name} | {t}")
open(os.path.join(ROOT, "data", "recent_topics.txt"), "w", encoding="utf-8").write("\n".join(out) + "\n")
print(len(out) - 2, "개")
