# -*- coding: utf-8 -*-
"""네이버 블로그용 '고르는 법 + 상품 비교' 글을 복사·붙여넣기 페이지로 만든다.
naver/queue/*.json 대본 → 쿠팡 API 로 상품 3개(로켓·가격대 다양하게) → docs/naver/<이름>.html
(맨 위 '글 복사하기' 버튼: 서식 그대로 복사 → 네이버 글쓰기에 붙여넣기) → 텔레그램으로 링크 알림.
네이버는 자동 발행 통로가 없어 발행 버튼은 관장님이 직접 누른다.
대본 형식: {"keyword": "온수매트", "title": "...", "intro": "<p>..</p>", "guide": "<h2>..</h2><p>..</p>",
          "faq": "<h3>..</h3><p>..</p>", "outro": "<p>..</p>", "tags": ["온수매트", ...]}"""
import glob
import html
import json
import os
import shutil
import sys
import time
import urllib.parse

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "instagram"))
os.environ.setdefault("COUPANG_SUB_ID", "naver")
import product_reel as pr  # noqa: E402

Q = os.path.join(ROOT, "naver", "queue")
DONE = os.path.join(ROOT, "naver", "done")
OUT = os.path.join(ROOT, "docs", "naver")
BASE = "https://baram-bot.github.io/blog-bot/naver/"
DISC = "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."


def products(kw, n=3):
    """같은 검색어에서 서로 다른 가격대 상품 3개(저·중·고)."""
    q = urllib.parse.urlencode({"keyword": kw, "limit": 10, "subId": pr.ca.SUB})
    items = (pr.ca._call("GET", f"{pr.ca.BASE}/products/search?{q}") or {}).get("productData", [])
    items = [p for p in items if p.get("productUrl") and p.get("productPrice")
             and not any(b in p.get("productName", "") for b in pr.ca.BLOCK)]
    items.sort(key=lambda p: (not p.get("isRocket"), p.get("rank", 99)))
    items = items[:8]
    items.sort(key=lambda p: p["productPrice"])
    if len(items) > n:  # 싼 것·중간·비싼 것 골고루
        idx = sorted({0, len(items) // 2, len(items) - 1})
        items = [items[i] for i in idx]
    out = []
    for p in items[:n]:
        link = p["productUrl"]
        try:
            short = pr.ca._call("POST", f"{pr.ca.BASE}/deeplink",
                                {"coupangUrls": [f"https://www.coupang.com/vp/products/{p['productId']}"], "subId": pr.ca.SUB}) or []
            link = (short[0] or {}).get("shortenUrl") or link
        except Exception as e:  # noqa: BLE001
            print(f"[네이버] 짧은 링크 실패: {e}")
        out.append({"name": p["productName"].strip(), "price": p["productPrice"], "rocket": bool(p.get("isRocket")),
                    "image": p.get("productImage", ""), "link": link})
        time.sleep(1)
    return out


def article(spec, prods):
    """네이버 편집기에 붙여 넣었을 때 모양이 살아남는 단순한 HTML(h2·h3·p·b·ul)."""
    rows = []
    for i, p in enumerate(prods, 1):
        rows.append(
            f'<h3>{i}. {html.escape(pr.short_name(p["name"], 48))}</h3>'
            + (f'<p><img src="{html.escape(p["image"])}" alt="" style="max-width:360px;width:100%"></p>' if p["image"] else "")
            + f'<p><b>가격대</b> {html.escape(pr.price_word(p["price"]))}'
            + (" · 로켓배송" if p["rocket"] else "") + " (작성일 기준, 바뀔 수 있어요)</p>"
            + f'<p>👉 <a href="{html.escape(p["link"])}">쿠팡에서 자세히 보기</a></p>')
    compare = "<h2>🛒 가격대별로 골라 봤어요</h2>" + "".join(rows)
    tags = " ".join("#" + t.lstrip("#").replace(" ", "") for t in spec.get("tags", []))
    return (f'<p><b>[광고]</b> {DISC}</p>' + spec.get("intro", "") + spec.get("guide", "") + compare
            + spec.get("faq", "") + spec.get("outro", "")
            + f'<p style="color:#888">※ {DISC} 가격·재고·혜택은 바뀔 수 있으니 구매 전 상세 페이지를 꼭 확인해 주세요.</p>'
            + (f"<p>{html.escape(tags)}</p>" if tags else ""))


def page(spec, body):
    t = html.escape(spec["title"])
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{t}</title><style>
body{{margin:0;background:#f4f4f6;font:17px/1.75 -apple-system,"Malgun Gothic","Noto Sans KR",sans-serif;color:#222}}
.bar{{position:sticky;top:0;background:#03c75a;color:#fff;padding:12px 16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;z-index:9}}
.bar button{{font:inherit;font-weight:800;border:0;border-radius:10px;padding:10px 16px;cursor:pointer}}
.b1{{background:#fff;color:#03c75a}}.b2{{background:#04a34a;color:#fff}}
.wrap{{max-width:760px;margin:16px auto;background:#fff;border-radius:14px;padding:24px 22px}}
#post h2{{font-size:24px;margin:28px 0 10px}}#post h3{{font-size:20px;margin:22px 0 8px}}
.title{{font-size:26px;font-weight:800;border:1px dashed #ccc;border-radius:10px;padding:10px 12px;margin-bottom:6px}}
.hint{{font-size:14px;color:#666}}
</style></head><body>
<div class="bar"><b>네이버 블로그 붙여넣기용</b>
<button class="b2" onclick="cp('ttl',false)">① 제목 복사</button>
<button class="b1" onclick="cp('post',true)">② 본문 복사</button><span id="m"></span></div>
<div class="wrap"><p class="hint">네이버 글쓰기 → 제목 칸에 ①, 본문 칸에 ② 붙여넣기(Ctrl+V) → 발행 전 한 번 훑어보고 발행</p>
<div class="title" id="ttl">{t}</div><div id="post">{body}</div></div>
<script>
async function cp(id,rich){{const el=document.getElementById(id);try{{
 if(rich&&window.ClipboardItem){{await navigator.clipboard.write([new ClipboardItem({{'text/html':new Blob([el.innerHTML],{{type:'text/html'}}),'text/plain':new Blob([el.innerText],{{type:'text/plain'}})}})]);}}
 else{{await navigator.clipboard.writeText(el.innerText);}}
 document.getElementById('m').textContent='✅ 복사됐어요';}}catch(e){{
 const r=document.createRange();r.selectNodeContents(el);const s=getSelection();s.removeAllRanges();s.addRange(r);document.execCommand('copy');
 document.getElementById('m').textContent='✅ 복사됐어요';}}}}
</script></body></html>"""


def tg(text):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if tok and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", data={"chat_id": chat, "text": text}, timeout=20)
        except Exception:  # noqa: BLE001
            pass


def main():
    files = sorted(glob.glob(os.path.join(Q, "*.json")))
    if not files:
        print("[네이버] 대기 대본 없음")
        return 0
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(DONE, exist_ok=True)
    made = []
    for f in files[:1]:  # 하루 1편
        name = os.path.splitext(os.path.basename(f))[0]
        spec = json.load(open(f, encoding="utf-8"))
        if spec.get("no_products"):  # 링크 없는 정보 글(블로그 점수 쌓기용)
            tags = " ".join("#" + t.lstrip("#").replace(" ", "") for t in spec.get("tags", []))
            body = spec.get("intro", "") + spec.get("guide", "") + spec.get("faq", "") + spec.get("outro", "") + \
                (f"<p>{html.escape(tags)}</p>" if tags else "")
            prods = []
        else:
            prods = products(spec["keyword"])
            if not prods:
                raise RuntimeError(f"상품을 못 찾음: {spec['keyword']}")
            body = article(spec, prods)
        open(os.path.join(OUT, name + ".html"), "w", encoding="utf-8").write(page(spec, body))
        shutil.move(f, os.path.join(DONE, os.path.basename(f)))
        made.append((name, spec["title"]))
        print(f"[네이버] {spec['title']} → {BASE}{name}.html ({len(prods)}개 상품)")
    pr.push("네이버 붙여넣기 글 [skip ci]", OUT, Q, DONE)
    time.sleep(60)  # 깃허브 페이지 반영 대기
    for name, title in made:
        tg(f"📝 오늘의 네이버 블로그 글이 준비됐어요 (꿀템 노트 아이디로 올려 주세요)\n{title}\n\n{BASE}{name}.html\n\n① 제목 복사 → ② 본문 복사 → 네이버에 붙여넣고 발행만 눌러 주세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
