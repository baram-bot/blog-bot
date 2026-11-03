# -*- coding: utf-8 -*-
"""블로그에 이미 올라간 글 전체에 '분야(카테고리) 라벨'을 하나씩 붙여 정리한다.

블로그 화면에서 /search/label/<분야> 로 분야별 글을 모아 볼 수 있게 된다.
기존 라벨(키워드)은 지우지 않고, 맨 앞에 분야 라벨 하나를 둔다(옛 분야 이름은 새 이름으로 바꿈).
실행: RELABEL_BLOG=econ|nohu, DRY_RUN=1 이면 바꾸지 않고 결과만 출력.
"""
import json
import os
import sys
import urllib.parse

import blog_bot as bb

BLOGS = {
    "econ": os.environ.get("BLOGGER_BLOG_ID", ""),
    "nohu": "8885340922893837263",
}

# 분야 이름(새 이름) ← 예전 첫 라벨, 제목·라벨 속 단어
CATS = {
    "econ": [
        ("AI·미래산업", {"AI·미래산업", "AI", "미래산업"},
         ("AI", "인공지능", "로봇", "자율주행", "반도체", "전기차", "배터리", "우주", "챗GPT", "데이터센터", "미래산업", "휴머노이드")),
        ("지원금·정책자금", {"지원금", "정책자금", "지원금·정책자금"},
         ("지원금", "바우처", "보조금", "정책자금", "지원사업", "환급", "신청")),
        ("재테크·금융", {"재테크", "재테크·금융", "금융"},
         ("적금", "예금", "금리", "ISA", "IRP", "연금저축", "대출", "신용", "절세", "연말정산", "세금", "통장", "재테크")),
        ("경영·창업", {"경영", "경영·창업", "창업"},
         ("사업자", "소상공인", "창업", "부가세", "노란우산", "사장님")),
        ("핫이슈", {"핫이슈"}, ("속보", "논란", "유출", "리콜", "급등", "급락")),
        ("생활경제", {"생활경제"}, ("물가", "요금", "난방비", "전기요금", "장보기", "김장", "생활")),
        ("여행·나들이", {"여행", "여행·나들이"},
         ("여행", "나들이", "가볼만한", "축제", "단풍", "캠핑", "드라이브")),
    ],
    "nohu": [
        ("연금", {"연금"}, ("연금", "노령", "수령")),
        ("노후 준비·일자리", {"일자리", "노후 준비·일자리", "노후"}, ("일자리", "재취업", "노후 준비", "은퇴")),
        ("상속·증여", {"상속", "증여", "상속·증여"}, ("상속", "증여", "유언", "유산")),
        ("건강보험·돌봄", {"건강보험", "돌봄", "건강", "건강보험·돌봄", "보험"},
         ("건강보험", "건보료", "피부양자", "장기요양", "돌봄", "치매", "보험", "건강")),
        ("생활·혜택", {"생활", "보훈", "생활·혜택"}, ("할인", "혜택", "보훈", "교통", "통신", "사기", "보이스피싱", "생활")),
    ],
}
# 여행 글(예전 바람살림 시절)의 첫 라벨은 지역 이름이라, 지역·여행 단어로도 잡는다
TRAVEL_HINT = ("경주", "속초", "가평", "청송", "정읍", "강릉", "제주", "부산", "여수", "전주", "서울근교", "경기도", "춘천")


def pick(kind, title, labels):
    cats = CATS[kind]
    names = {c[0] for c in cats}
    for lab in labels:  # 이미 새 분야 이름이 붙어 있으면 그대로
        if lab in names:
            return lab
    for lab in labels[:1]:  # 예전 첫 라벨(분야)
        for name, olds, _ in cats:
            if lab in olds:
                return name
    if kind == "econ" and any(h in " ".join(labels) + title for h in TRAVEL_HINT):
        return "여행·나들이"
    text = title + " " + " ".join(labels)
    best, score = None, 0
    for name, _, words in cats:
        s = sum(text.count(w) for w in words)
        if s > score:
            best, score = name, s
    return best or ("생활경제" if kind == "econ" else "생활·혜택")


def all_posts(blog_id, token):
    out, page = [], None
    while True:
        q = {"maxResults": "500", "fetchBodies": "false", "status": "live"}
        if page:
            q["pageToken"] = page
        url = f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts?" + urllib.parse.urlencode(q)
        js = bb.http_json(url, headers={"Authorization": f"Bearer {token}"})
        out += js.get("items", [])
        page = js.get("nextPageToken")
        if not page:
            return out


def main():
    kind = os.environ.get("RELABEL_BLOG", "econ")
    dry = os.environ.get("DRY_RUN") == "1"
    blog_id = BLOGS[kind]
    token = bb.google_access_token()
    posts = all_posts(blog_id, token)
    old_names = {o for _, olds, _ in CATS[kind] for o in olds} | {c[0] for c in CATS[kind]}
    counts = {}
    for p in posts:
        labels = p.get("labels", []) or []
        cat = pick(kind, p.get("title", ""), labels)
        counts[cat] = counts.get(cat, 0) + 1
        rest = [l for l in labels if l not in old_names]
        new = ([cat] + rest)[:20]
        if new == labels:
            continue
        print(f"[{cat}] {p.get('title', '')[:40]}  {labels} → {new}")
        if dry:
            continue
        url = f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts/{p['id']}"
        try:
            bb.http_json(url, data={"labels": new}, headers={"Authorization": f"Bearer {token}"}, method="PATCH")
        except Exception as e:  # noqa: BLE001
            print(f"  ! 실패: {str(e)[:200]}")
    print("분야별 글 수:", json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
