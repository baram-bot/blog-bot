#!/usr/bin/env python3
"""바람따라 한국여행 블로그 자동 발행 봇.

GitHub Actions에서 실행된다.
1) topics.txt에서 아직 안 쓴 주제를 하나 고른다.
2) Gemini API로 한국어 여행 글(HTML)을 쓴다.
3) 위키미디어 공용(자유 이용 사진)에서 대표 사진을 찾는다.
4) 어울리는 쿠팡 파트너스 상품이 있으면 대가성 문구와 함께 넣는다.
5) Blogger API로 바로 발행하고, 텔레그램으로 알린다.

외부 패키지 없이 파이썬 표준 라이브러리만 쓴다.
"""

import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
TOPICS_FILE = os.path.join(ROOT, "topics.txt")
LINKS_FILE = os.path.join(ROOT, "data", "coupang_links.txt")
STATE_FILE = os.path.join(ROOT, "data", "posted.json")

KST = dt.timezone(dt.timedelta(hours=9))
DISCLOSURE = "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
USER_AGENT = "baram-blog-bot/1.0 (personal travel blog; github actions)"

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


# ---------------------------------------------------------------- 공통 도구

def env(name, required=True, default=""):
    value = os.environ.get(name, "").strip()
    if required and not value:
        raise SystemExit(f"[설정 오류] GitHub 비밀값 {name} 이(가) 비어 있습니다.")
    return value or default


def http_json(url, data=None, headers=None, method=None, timeout=120):
    headers = dict(headers or {})
    headers.setdefault("User-Agent", USER_AGENT)
    body = None
    if data is not None:
        if isinstance(data, (dict, list)):
            body = json.dumps(data).encode("utf-8")
            headers.setdefault("Content-Type", "application/json; charset=utf-8")
        elif isinstance(data, str):
            body = data.encode("utf-8")
        else:
            body = data
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:800]
        raise RuntimeError(f"HTTP {e.code} {url.split('?')[0]}: {detail}") from None


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"posted": [], "used_links": []}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def topic_id(topic):
    return hashlib.md5(topic.encode("utf-8")).hexdigest()[:10]


# ---------------------------------------------------------------- 주제 고르기

def read_topics():
    """topics.txt 형식: 주제 | 대표사진 검색어(선택) | 쿠팡상품 분류(선택)"""
    topics = []
    with open(TOPICS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            topics.append({
                "title": parts[0],
                "photo": parts[1] if len(parts) > 1 else "",
                "category": parts[2] if len(parts) > 2 else "",
            })
    return topics


def pick_topic(state):
    done = {p["id"] for p in state["posted"]}
    for t in read_topics():
        if topic_id(t["title"]) not in done:
            return t
    return None


# ---------------------------------------------------------------- 쿠팡 링크

def read_links():
    """data/coupang_links.txt 형식: 링크 | 상품명 | 분류"""
    links = []
    if not os.path.exists(LINKS_FILE):
        return links
    with open(LINKS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2 or not parts[0].startswith("https://link.coupang.com/"):
                continue
            links.append({
                "url": parts[0],
                "name": parts[1],
                "category": parts[2] if len(parts) > 2 else "",
            })
    return links


def pick_link(topic, state):
    links = read_links()
    if not links:
        return None
    used = state.get("used_links", [])
    wanted = topic.get("category", "")
    matching = [l for l in links if wanted and l["category"] == wanted]
    pool = matching or [l for l in links if l["category"] in ("", "여행공통")]
    if not pool:
        return None
    # 가장 오래전에 쓴(또는 한 번도 안 쓴) 링크부터
    pool.sort(key=lambda l: used.index(l["url"]) if l["url"] in used else -1)
    return pool[0]


# ---------------------------------------------------------------- Gemini

def choose_models(api_key):
    """쓸 수 있는 Gemini 모델 목록(좋은 순서). 무료 사용량이 없는 모델은 실행 중에 건너뛴다."""
    forced = os.environ.get("GEMINI_MODEL", "").strip()
    if forced:
        return [forced]
    try:
        data = http_json(f"{GEMINI_BASE}/models?pageSize=200&key={api_key}", timeout=30)
    except Exception as e:  # noqa: BLE001
        print(f"[Gemini] 모델 목록 조회 실패: {e}")
        data = {}
    main, lite = [], []
    for m in data.get("models", []):
        name = m.get("name", "").replace("models/", "")
        methods = m.get("supportedGenerationMethods", [])
        if "generateContent" not in methods:
            continue
        low = name.lower()
        if "flash" not in low:
            continue
        if any(bad in low for bad in ("image", "tts", "audio", "live", "embedding", "thinking-exp")):
            continue
        nums = re.findall(r"\d+(?:\.\d+)?", low)
        version = float(nums[0]) if nums else 0.0
        preview = ("preview" in low) or ("exp" in low)
        (lite if "lite" in low else main).append((not preview, version, name))
    main.sort(reverse=True)
    lite.sort(reverse=True)
    models = [n for _, _, n in main] + [n for _, _, n in lite]
    for fallback in ("gemini-2.5-flash", "gemini-2.5-flash-lite"):
        if fallback not in models:
            models.append(fallback)
    return models


def gemini_generate(api_key, model, prompt, use_search=True):
    url = f"{GEMINI_BASE}/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.8, "maxOutputTokens": 8192},
    }
    if use_search:
        payload["tools"] = [{"google_search": {}}]
    data = http_json(url, data=payload, timeout=180)
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts)
    if not text.strip():
        raise RuntimeError(f"Gemini 응답이 비어 있습니다: {json.dumps(data)[:500]}")
    return text


def build_prompt(topic, today):
    season = {12: "겨울", 1: "겨울", 2: "겨울", 3: "봄", 4: "봄", 5: "봄",
              6: "여름", 7: "여름", 8: "여름"}.get(today.month, "가을")
    return f"""너는 한국 국내여행 블로그 '바람따라 한국여행'의 작가다.
오늘은 {today:%Y년 %m월 %d일}({season})이다. 아래 주제로 블로그 글 1편을 써라.

주제: {topic['title']}

[독자] 국내여행을 계획하는 30~60대. 주말·가족·부부 여행을 많이 간다.

[내용 원칙 — 반드시 지킬 것]
- 구글 검색으로 확인한 사실만 쓴다. 확인되지 않은 입장료·운영시간·전화번호·주차요금·메뉴 가격은 쓰지 말고 "방문 전 공식 안내를 확인해 주세요"라고 쓴다.
- 존재하지 않는 장소·식당·행사를 지어내지 않는다. 특정 식당을 추천할 때는 실제로 확인된 곳만, 상호명과 대표 메뉴 정도만 쓴다.
- "제가 가봤는데", "직접 먹어보니"처럼 직접 다녀온 척하는 표현은 쓰지 않는다. 안내자 시점으로 쓴다.
- 계절({season})과 지금 시기에 맞는 정보(꽃·단풍·축제·날씨·옷차림)를 반영한다.
- 독자가 실제로 일정을 짤 수 있게 구체적으로 쓴다: 가는 법(대중교통·자가용), 추천 동선, 소요 시간, 함께 들르기 좋은 곳, 여행 팁.

[형식]
- 공백 포함 2,500~3,500자.
- 본문은 HTML로 쓴다. 쓸 수 있는 태그: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <table>, <tr>, <th>, <td>. 다른 태그·스타일·스크립트 금지.
- 구성: 도입(2~3문장, 왜 지금 가기 좋은지) → <h2> 소제목 4~6개 → 마지막 <h2>여행 정리</h2>에 한눈에 보는 요약 표.
- 문체: 친근하고 정확한 존댓말. 과장 광고 표현 금지. 이모지 금지.

[출력] 설명 없이 아래 JSON 하나만 출력한다(코드블록 표시 없이).
{{"title": "검색에 잘 걸리는 제목(40자 이내, 지역명+핵심 키워드 포함)",
  "description": "검색 결과에 보일 요약(120자 이내)",
  "labels": ["지역명", "여행 종류", "계절" 등 3~6개],
  "html": "본문 HTML"}}
"""


def parse_article(text):
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("JSON을 찾지 못했습니다")
    obj = json.loads(cleaned[start:end + 1])
    for key in ("title", "html"):
        if not str(obj.get(key, "")).strip():
            raise ValueError(f"{key} 항목이 비어 있습니다")
    obj["labels"] = [str(x).strip() for x in obj.get("labels", []) if str(x).strip()][:6]
    obj["description"] = str(obj.get("description", "")).strip()
    return obj


ALLOWED_TAGS = {"h2", "h3", "p", "ul", "ol", "li", "strong", "b", "em", "table",
                "thead", "tbody", "tr", "th", "td", "br"}


def sanitize_html(body):
    # 허용하지 않는 태그는 지우고(내용은 남김), 모든 속성을 없앤다.
    body = re.sub(r"<\s*(script|style|iframe)[^>]*>.*?<\s*/\s*\1\s*>", "", body, flags=re.S | re.I)

    def fix(match):
        closing, tag = match.group(1), match.group(2).lower()
        if tag not in ALLOWED_TAGS:
            return ""
        return f"<{closing}{tag}>"

    return re.sub(r"<\s*(/?)\s*([a-zA-Z0-9]+)[^>]*>", fix, body)


def check_article(article):
    text = re.sub(r"<[^>]+>", "", article["html"])
    length = len(text)
    problems = []
    if length < 1500:
        problems.append(f"본문이 너무 짧음({length}자)")
    for phrase in ("제가 가봤", "직접 가봤", "직접 먹어", "제가 먹어", "최저가 보장"):
        if phrase in text:
            problems.append(f"금지 표현 포함: {phrase}")
    return problems


def write_article(topic, today):
    api_key = env("GEMINI_API_KEY")
    models = choose_models(api_key)
    print(f"[Gemini] 후보 모델: {', '.join(models[:6])}")
    prompt = build_prompt(topic, today)
    last_error = None
    for model in models[:6]:
        for use_search in (True, False):  # 검색 사용 → 실패하면 검색 없이 한 번 더
            try:
                text = gemini_generate(api_key, model, prompt, use_search=use_search)
                article = parse_article(text)
                article["html"] = sanitize_html(article["html"])
                problems = check_article(article)
                if problems:
                    raise ValueError(", ".join(problems))
                article["model"] = model
                article["searched"] = use_search
                print(f"[Gemini] 사용 모델: {model} (검색 {'사용' if use_search else '안 함'})")
                return article
            except Exception as e:  # noqa: BLE001
                last_error = e
                short = str(e).split("\n")[0][:200]
                print(f"[Gemini] {model} 실패: {short}")
                if "HTTP 429" in str(e) or "HTTP 404" in str(e):
                    break  # 이 모델은 무료 사용량이 없거나 없는 모델 → 다음 모델로
                time.sleep(5)
    raise RuntimeError(f"글 작성 실패: {str(last_error)[:300]}")


# ---------------------------------------------------------------- 사진(위키미디어 공용)

def find_photo(query):
    if not query:
        return None
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": "6", "gsrlimit": "10",
        "prop": "imageinfo", "iiprop": "url|extmetadata|size", "iiurlwidth": "1200",
    }
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    try:
        data = http_json(url, timeout=30)
    except Exception as e:  # noqa: BLE001
        print(f"[사진] 검색 실패: {e}")
        return None
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        license_name = meta.get("LicenseShortName", {}).get("value", "")
        if not license_name or "fair use" in license_name.lower():
            continue
        if info.get("width", 0) < 800 or info.get("width", 0) < info.get("height", 0):
            continue  # 작거나 세로 사진은 건너뛴다
        artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip() or "작성자 미상"
        return {
            "src": info.get("thumburl") or info.get("url"),
            "page": info.get("descriptionurl", ""),
            "credit": f"사진: {artist[:60]} / {license_name} / 위키미디어 공용",
        }
    return None


# ---------------------------------------------------------------- 글 조립

def assemble(article, photo, link):
    parts = []
    if link:
        parts.append(f'<p style="font-size:13px;color:#777">{html.escape(DISCLOSURE)}</p>')
    if photo:
        alt = html.escape(article["title"])
        parts.append(
            '<div style="text-align:center;margin:0 0 20px">'
            f'<img src="{html.escape(photo["src"])}" alt="{alt}" style="max-width:100%;height:auto;border-radius:8px" loading="lazy">'
            f'<div style="font-size:12px;color:#888;margin-top:6px"><a href="{html.escape(photo["page"])}" rel="nofollow noopener" target="_blank">{html.escape(photo["credit"])}</a></div>'
            "</div>"
        )
    parts.append(article["html"])
    if link:
        parts.append(
            '<div style="border:1px solid #e3e3e3;border-radius:10px;padding:16px;margin:28px 0;background:#fafafa">'
            '<p style="margin:0 0 8px;font-weight:bold">여행 준비물 추천</p>'
            f'<p style="margin:0 0 10px">{html.escape(link["name"])}</p>'
            f'<p style="margin:0"><a href="{html.escape(link["url"])}" rel="sponsored nofollow noopener" target="_blank">쿠팡에서 보기 &rarr;</a></p>'
            "</div>"
        )
    parts.append('<p style="font-size:13px;color:#888">운영시간·요금·행사 일정은 바뀔 수 있으니 방문 전 공식 안내를 꼭 확인해 주세요.</p>')
    return "\n".join(parts)


# ---------------------------------------------------------------- Blogger

def google_access_token():
    data = urllib.parse.urlencode({
        "client_id": env("GOOGLE_CLIENT_ID"),
        "client_secret": env("GOOGLE_CLIENT_SECRET"),
        "refresh_token": env("GOOGLE_REFRESH_TOKEN"),
        "grant_type": "refresh_token",
    })
    res = http_json("https://oauth2.googleapis.com/token", data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    token = res.get("access_token")
    if not token:
        raise RuntimeError(f"구글 토큰 발급 실패: {res}")
    return token


def publish(article, content):
    blog_id = env("BLOGGER_BLOG_ID")
    token = google_access_token()
    body = {
        "kind": "blogger#post",
        "title": article["title"],
        "content": content,
        "labels": article["labels"],
    }
    url = f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts/?isDraft=false"
    res = http_json(url, data=body, headers={"Authorization": f"Bearer {token}"}, method="POST")
    return res.get("url", ""), res.get("id", "")


# ---------------------------------------------------------------- 텔레그램

def notify(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return
    try:
        http_json(f"https://api.telegram.org/bot{token}/sendMessage",
                  data={"chat_id": chat_id, "text": message, "disable_web_page_preview": False},
                  timeout=30)
    except Exception as e:  # noqa: BLE001
        print(f"[텔레그램] 알림 실패: {e}")


# ---------------------------------------------------------------- 실행

POSTS_DIR = os.path.join(ROOT, "posts")


def next_queued_post(state):
    """posts/ 폴더에서 아직 안 올린 글(json) 중 이름순으로 가장 앞의 것."""
    if not os.path.isdir(POSTS_DIR):
        return None, None
    done = {p.get("file") for p in state["posted"] if p.get("file")}
    for name in sorted(os.listdir(POSTS_DIR)):
        if not name.endswith(".json") or name in done:
            continue
        path = os.path.join(POSTS_DIR, name)
        try:
            with open(path, encoding="utf-8") as f:
                obj = json.load(f)
            for key in ("title", "html"):
                if not str(obj.get(key, "")).strip():
                    raise ValueError(f"{key} 비어 있음")
        except Exception as e:  # noqa: BLE001
            print(f"[대기 글] {name} 읽기 실패, 건너뜀: {e}")
            state["posted"].append({"file": name, "skipped": str(e)[:200]})
            continue
        return name, obj
    return None, None


def publish_queued(state, today, dry_run):
    name, obj = next_queued_post(state)
    if not name:
        return None
    print(f"[대기 글] {name}: {obj['title']}")
    article = {
        "title": str(obj["title"]).strip(),
        "html": sanitize_html(obj["html"]),
        "labels": [str(x).strip() for x in obj.get("labels", []) if str(x).strip()][:6],
    }
    problems = [p for p in check_article(article) if "너무 짧음" in p]
    if problems:
        print(f"[대기 글] 경고: {', '.join(problems)}")
    photo = find_photo(obj.get("photo") or article["title"])
    link = pick_link({"category": obj.get("category", "")}, state)
    content = assemble(article, photo, link)
    if dry_run:
        with open(os.path.join(ROOT, "preview.html"), "w", encoding="utf-8") as f:
            f.write(f"<h1>{html.escape(article['title'])}</h1>\n{content}")
        print("[시험] preview.html 저장")
        return 0
    try:
        post_url, post_id = publish(article, content)
    except Exception as e:  # noqa: BLE001
        msg = f"[블로그] 발행 실패\n글: {article['title']}\n원인: {str(e)[:300]}"
        print(msg)
        notify(msg)
        return 1
    state["posted"].append({
        "file": name, "title": article["title"], "url": post_url, "post_id": post_id,
        "at": today.strftime("%Y-%m-%d %H:%M"), "model": "claude", "link": link["url"] if link else "",
    })
    if link:
        used = [u for u in state.get("used_links", []) if u != link["url"]]
        used.append(link["url"])
        state["used_links"] = used
    save_state(state)
    left = sum(1 for n in os.listdir(POSTS_DIR) if n.endswith(".json")) - len(
        [p for p in state["posted"] if p.get("file")])
    msg = f"[블로그] 새 글 발행\n{article['title']}\n{post_url}\n남은 대기 글: {max(left, 0)}편"
    print(msg)
    notify(msg)
    return 0


def main():
    dry_run = "--dry-run" in sys.argv
    today = dt.datetime.now(KST)
    state = load_state()

    # 1순위: Claude가 미리 써 둔 대기 글(posts/)
    result = publish_queued(state, today, dry_run)
    if result is not None:
        return result

    # 2순위: Gemini로 직접 쓰기 (USE_GEMINI=1 일 때만)
    if os.environ.get("USE_GEMINI", "").strip() != "1":
        msg = "[블로그] 올릴 대기 글이 없어 이번 회차는 건너뜁니다."
        print(msg)
        return 0

    topic = pick_topic(state)
    if not topic:
        msg = "[블로그] topics.txt의 주제를 모두 썼습니다. 새 주제를 추가해 주세요."
        print(msg)
        notify(msg)
        return 0

    print(f"[주제] {topic['title']}")
    try:
        article = write_article(topic, today)
        photo = find_photo(topic["photo"] or topic["title"])
        link = pick_link(topic, state)
        content = assemble(article, photo, link)

        if dry_run:
            out = os.path.join(ROOT, "preview.html")
            with open(out, "w", encoding="utf-8") as f:
                f.write(f"<h1>{html.escape(article['title'])}</h1>\n{content}")
            print(f"[시험] 발행하지 않고 {out} 에 저장했습니다.")
            return 0

        post_url, post_id = publish(article, content)
    except Exception as e:  # noqa: BLE001
        msg = f"[블로그] 발행 실패\n주제: {topic['title']}\n원인: {str(e)[:300]}"
        print(msg)
        notify(msg)
        return 1

    state["posted"].append({
        "id": topic_id(topic["title"]),
        "topic": topic["title"],
        "title": article["title"],
        "url": post_url,
        "post_id": post_id,
        "at": today.strftime("%Y-%m-%d %H:%M"),
        "model": article.get("model", ""),
        "link": link["url"] if link else "",
    })
    if link:
        used = [u for u in state.get("used_links", []) if u != link["url"]]
        used.append(link["url"])
        state["used_links"] = used
    save_state(state)

    remaining = len(read_topics()) - len(state["posted"])
    msg = f"[블로그] 새 글 발행\n{article['title']}\n{post_url}\n남은 주제: {remaining}개"
    print(msg)
    notify(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
