# -*- coding: utf-8 -*-
"""실시간 검색·화제 데이터 수집기.

매시간 GitHub Actions에서 실행되어 data/trends.json 을 만든다.
블로그 글 작업(Claude)은 이 파일을 먼저 읽고 주제를 고른다.
각 출처는 따로 시도하고, 실패한 출처는 errors 에 기록만 하고 넘어간다.
"""
import datetime as dt
import html
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "data", "trends.json")
KST = dt.timezone(dt.timedelta(hours=9))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def get(url, timeout=20, encoding=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        charset = encoding or r.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def clean(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def google_trends():
    """구글 트렌드 한국 실시간 급상승 검색어 (대략적 검색량 포함)."""
    xml = get("https://trends.google.com/trending/rss?geo=KR")
    root = ET.fromstring(xml)
    ns = {"ht": "https://trends.google.com/trending/rss"}
    out = []
    for it in root.iter("item"):
        news = []
        for n in it.findall("ht:news_item", ns):
            news.append({
                "title": clean(n.findtext("ht:news_item_title", default="", namespaces=ns)),
                "source": clean(n.findtext("ht:news_item_source", default="", namespaces=ns)),
                "url": n.findtext("ht:news_item_url", default="", namespaces=ns),
            })
        out.append({
            "keyword": clean(it.findtext("title")),
            "approx_traffic": clean(it.findtext("ht:approx_traffic", default="", namespaces=ns)),
            "pubDate": it.findtext("pubDate", default=""),
            "news": news[:3],
        })
    return out


def naver_realtime_keywords():
    """네이버 기반 실시간 검색어 집계 (signal.bz)."""
    data = json.loads(get("https://api.signal.bz/news/realtime"))
    rows = data.get("top10") or data.get("data") or []
    return [{"rank": r.get("rank"), "keyword": r.get("keyword"), "state": r.get("state")} for r in rows]


def naver_news_ranking():
    """네이버 뉴스 언론사별 많이 본 뉴스."""
    page = get("https://news.naver.com/main/ranking/popularDay.naver")
    out = []
    parts = re.split(r'class="rankingnews_name[^"]*"', page)
    for part in parts[1:]:
        press = clean(part[part.find(">") + 1: part.find("<")])
        block = part.split("rankingnews_name")[0]
        links = re.findall(r'<a href="([^"]+)"[^>]*class="list_title[^"]*"[^>]*>(.*?)</a>', block, re.S)
        if not links:
            links = re.findall(r'class="list_title[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        for rank, (url, title) in enumerate(links[:5], 1):
            out.append({"press": press, "rank": rank, "title": clean(title), "url": url})
    return out


def nate_live_keywords():
    """네이트 실시간 이슈 키워드."""
    raw = get("https://www.nate.com/js/data/jsonLiveKeywordDataV1.js", encoding="euc-kr")
    data = json.loads(raw[raw.find("["): raw.rfind("]") + 1])
    out = []
    for i, row in enumerate(data[:10], 1):
        kw = row[1] if isinstance(row, list) and len(row) > 1 else row
        out.append({"rank": i, "keyword": clean(str(kw))})
    return out


def naver_section(sid, name):
    """네이버 뉴스 섹션 헤드라인(경제=101, 생활=103, 사회=102)."""
    page = get(f"https://news.naver.com/section/{sid}")
    titles = re.findall(r'class="sa_text_strong"[^>]*>(.*?)</strong>', page, re.S)
    seen, out = set(), []
    for t in titles:
        t = clean(t)
        if t and t not in seen:
            seen.add(t)
            out.append({"section": name, "title": t})
    return out[:30]


def daum_ranking():
    """다음 뉴스 많이 본 뉴스."""
    page = get("https://news.daum.net/ranking/popular")
    titles = re.findall(r'<a[^>]+class="link_txt"[^>]*>(.*?)</a>', page, re.S)
    if not titles:
        titles = re.findall(r'<strong class="tit_txt"[^>]*>(.*?)</strong>', page, re.S)
    return [{"rank": i, "title": clean(t)} for i, t in enumerate(titles[:50], 1) if clean(t)]


def google_news(topic):
    """구글 뉴스 한국판 섹션 헤드라인."""
    url = f"https://news.google.com/rss/headlines/section/topic/{topic}?hl=ko&gl=KR&ceid=KR:ko"
    root = ET.fromstring(get(url))
    return [{"title": clean(it.findtext("title")), "pubDate": it.findtext("pubDate", default="")}
            for it in list(root.iter("item"))[:30]]


def main():
    result = {"collected_at_kst": dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "errors": {}}
    jobs = {
        "google_trends_kr": google_trends,
        "naver_realtime_keywords": naver_realtime_keywords,
        "naver_most_viewed": naver_news_ranking,
        "naver_economy": lambda: naver_section(101, "경제"),
        "naver_life": lambda: naver_section(103, "생활/문화"),
        "naver_society": lambda: naver_section(102, "사회"),
        "nate_live_keywords": nate_live_keywords,
        "google_news_business": lambda: google_news("BUSINESS"),
        "google_news_top": lambda: google_news("NATION"),
    }
    for key, fn in jobs.items():
        try:
            result[key] = fn()
        except Exception as e:  # 한 출처가 막혀도 나머지는 계속
            result[key] = []
            result["errors"][key] = f"{type(e).__name__}: {str(e)[:200]}"
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    counts = {k: len(v) for k, v in result.items() if isinstance(v, list)}
    print(json.dumps({"counts": counts, "errors": result["errors"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
