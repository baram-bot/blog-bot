# -*- coding: utf-8 -*-
"""인스타 '생활 꿀템' 릴스 (하루 1편).
instagram/products/queue/*.json 대본(검색어·첫 문장·고르는 법 3가지·캡션)을 읽어
1) 쿠팡 파트너스 API 로 실제 상품(로켓배송·적당한 가격) 1개를 고르고
2) 상품 사진으로 1080x1920 세로 영상(AI 음성 + 큰 자막 + 화면 내내 '광고' 표시)을 만들고
3) 링크 모음 페이지(docs/index.html)에 번호를 붙여 올린 뒤
4) 인스타 릴스로 게시한다. DRY=1 이면 영상만 만들고 게시하지 않는다.
대본 형식: {"search": ["온수매트", "전기요"], "hook": "...", "points": ["...", "...", "..."],
          "clips": [{"query": "영어 검색어", "text": "짤 위 큰 자막"}] (선택, 최대 3개 — 앞부분 고민·공감 짤),
          "bridge": "그래서 준비했다!" (짤 다음 상품으로 넘어가는 한마디, 선택),
          "closing": "...", "caption": "...", "tags": ["#..."]}"""
import datetime as dt
import glob
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse

import requests
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "shorts"))
os.environ.setdefault("COUPANG_SUB_ID", "instagram")
import coupang_api as ca  # noqa: E402
import make_cards as mc  # noqa: E402
import make_reel as mr  # noqa: E402
import post_reel as pr  # noqa: E402

Q = os.path.join(ROOT, "instagram", "products", "queue")
DONE = os.path.join(ROOT, "instagram", "products", "done")
LOG = os.path.join(ROOT, "data", "ig_products.json")
PAGE = os.path.join(ROOT, "docs", "index.html")  # 깃허브 Pages(main 브랜치 /docs 폴더)로 공개
LINKS_URL = os.environ.get("LINKS_URL", "https://baram-bot.github.io/blog-bot/")
HANDLE = "@gureum_happy_story"
W, H = 1080, 1920
ACC = (255, 107, 53)
INK = (30, 30, 34)
AD = "광고 · 쿠팡 파트너스 활동으로 수수료를 받아요"
DISCLOSURE = "[광고] 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."


def kst():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))


def load_log():
    return json.load(open(LOG, encoding="utf-8")) if os.path.exists(LOG) else {"items": []}


# ── 상품 고르기 ─────────────────────────────
def pick(search, used):
    for kw in search[:2]:
        q = urllib.parse.urlencode({"keyword": kw, "limit": 10, "subId": ca.SUB})
        items = (ca._call("GET", f"{ca.BASE}/products/search?{q}") or {}).get("productData", [])
        ok = [p for p in items if p.get("productImage") and p.get("productUrl")
              and str(p.get("productId")) not in used
              and not any(b in p.get("productName", "") for b in ca.BLOCK)]
        if not ok:
            print(f"[꿀템] '{kw}' 맞는 상품 없음")
            continue
        ok.sort(key=lambda p: (not p.get("isRocket"), not (5000 <= (p.get("productPrice") or 0) <= 60000), p.get("rank", 99)))
        p = ok[0]
        link = p["productUrl"]
        try:
            short = ca._call("POST", f"{ca.BASE}/deeplink",
                             {"coupangUrls": [f"https://www.coupang.com/vp/products/{p['productId']}"], "subId": ca.SUB}) or []
            link = (short[0] or {}).get("shortenUrl") or link
        except Exception as e:  # noqa: BLE001
            print(f"[꿀템] 짧은 링크 실패(긴 링크 사용): {e}")
        print(f"[꿀템] '{kw}' → {p['productName'][:50]} {p.get('productPrice')}원 로켓={p.get('isRocket')}")
        return {"id": str(p["productId"]), "name": p["productName"].strip(), "price": p.get("productPrice"),
                "rocket": bool(p.get("isRocket")), "image": p["productImage"], "link": link, "kw": kw}
    return None


def short_name(name, n=22):
    name = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", name).strip()
    return name if len(name) <= n else name[:n].rstrip() + "…"


def price_word(p):
    if not p:
        return ""
    if p < 10000:
        return f"{p:,}원"
    man, rest = divmod(p, 10000)
    return f"{man}만 {rest // 1000}천 원대" if rest >= 1000 else f"{man}만 원대"


# ── 화면 만들기 ─────────────────────────────
def badge(img):
    d = ImageDraw.Draw(img)
    f = mc.font("bold", 30)
    tw = d.textlength(AD, font=f)
    d.rounded_rectangle([40, 70, 40 + tw + 44, 126], radius=28, fill=(0, 0, 0))
    d.text((62, 78), AD, font=f, fill=(255, 255, 255))
    fh = mc.font("reg", 30)
    d.text(((W - d.textlength(HANDLE, font=fh)) / 2, H - 90), HANDLE, font=fh, fill=(150, 150, 150))
    return img


def product_card(photo, size):
    im = photo.copy()
    im.thumbnail((size, size))
    card = Image.new("RGB", (size, size), (255, 255, 255))
    card.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size, size], radius=40, fill=255)
    return card, mask


def centered(d, text, f, y, fill, maxw=W - 140, gap=1.25):
    for ln in mc.wrap(d, mc.noemo(text), f, maxw):
        d.text(((W - d.textlength(ln, font=f)) / 2, y), ln, font=f, fill=fill)
        y += int(f.size * gap)
    return y


def frame_hook(photo, hook):
    bg = photo.copy().convert("RGB")
    r = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * r) + 1, int(bg.height * r) + 1)).crop((0, 0, W, H))
    bg = bg.filter(ImageFilter.GaussianBlur(28))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.55)
    d = ImageDraw.Draw(bg)
    y = centered(d, hook, mc.font("black", 96), 300, (255, 255, 255))
    card, mask = product_card(photo, 760)
    bg.paste(card, ((W - 760) // 2, max(y + 60, 860)), mask)
    return badge(bg)


def frame_point(photo, i, text):
    img = Image.new("RGB", (W, H), (255, 248, 240))
    card, mask = product_card(photo, 620)
    img.paste(card, ((W - 620) // 2, 210), mask)
    d = ImageDraw.Draw(img)
    fnum = mc.font("black", 110)
    num = f"{i:02d}"
    d.text(((W - d.textlength(num, font=fnum)) / 2, 900), num, font=fnum, fill=ACC)
    centered(d, text, mc.font("black", 76), 1060, INK)
    return badge(img)


def frame_product(photo, prod, no):
    img = Image.new("RGB", (W, H), (255, 255, 255))
    card, mask = product_card(photo, 760)
    img.paste(card, ((W - 760) // 2, 200), mask)
    d = ImageDraw.Draw(img)
    y = centered(d, short_name(prod["name"], 34), mc.font("bold", 56), 1010, INK)
    y += 20
    tags = [price_word(prod["price"])] + (["로켓배송"] if prod["rocket"] else [])
    f = mc.font("black", 54)
    widths = [d.textlength(t, font=f) + 60 for t in tags]
    x = (W - sum(widths) - 24 * (len(tags) - 1)) / 2
    for t, w in zip(tags, widths):
        d.rounded_rectangle([x, y, x + w, y + 90], radius=45, fill=ACC)
        d.text((x + 30, y + 10), t, font=f, fill=(255, 255, 255))
        x += w + 24
    y += 150
    d.rounded_rectangle([90, y, W - 90, y + 150], radius=40, fill=INK)
    t = f"프로필 링크  →  {no}번"
    fl = mc.font("black", 66)
    d.text(((W - d.textlength(t, font=fl)) / 2, y + 30), t, font=fl, fill=(255, 255, 255))
    d.text((90, y + 180), "가격·재고는 바뀔 수 있어요(오늘 기준)", font=mc.font("reg", 34), fill=(140, 140, 140))
    return badge(img)


def frame_bridge(photo, text):
    """짤(고민) → 상품(해결)을 잇는 장면: '그래서 준비했다!' + 상품이 크게 등장."""
    img = Image.new("RGB", (W, H), ACC)
    d = ImageDraw.Draw(img)
    y = centered(d, text, mc.font("black", 120), 260, (255, 255, 255))
    card, mask = product_card(photo, 820)
    img.paste(card, ((W - 820) // 2, max(y + 60, 700)), mask)
    return badge(img)


def frame_cta(photo, closing):
    img = Image.new("RGB", (W, H), ACC)
    d = ImageDraw.Draw(img)
    y = centered(d, closing or "필요할 때 꺼내 보시게 저장해 두세요", mc.font("black", 88), 600, (255, 255, 255))
    y += 80
    for t in ("저장해 두고 필요할 때 꺼내 보세요", "매일 생활 꿀템 하나씩 골라 드려요"):
        y = centered(d, t, mc.font("bold", 50), y, (255, 255, 255)) + 20
    by = H - 420
    d.rounded_rectangle([80, by, W - 80, by + 190], radius=40, fill=(255, 255, 255))
    centered(d, "팔로우하고 꿀템 받아 보기", mc.font("black", 56), by + 30, ACC)
    centered(d, HANDLE, mc.font("bold", 42), by + 112, INK)
    return badge(img)


PEXELS = os.environ.get("PEXELS_API_KEY", "").strip()
PIXABAY = os.environ.get("PIXABAY_API_KEY", "").strip()


def stock_url(query):
    """무료 영상 주소 하나: Pixabay(키 있으면) → Pexels 순."""
    if PIXABAY:
        try:
            js = requests.get("https://pixabay.com/api/videos/", params={"key": PIXABAY, "q": query, "safesearch": "true",
                                                                         "per_page": 10, "video_type": "film"}, timeout=30).json()
            for h in js.get("hits", []):
                v = h.get("videos", {})
                for k in ("medium", "large", "small"):
                    if (v.get(k) or {}).get("url") and (v[k].get("height") or 0) >= 720:
                        return v[k]["url"]
        except Exception as e:  # noqa: BLE001
            print(f"[꿀템] Pixabay 실패: {e}")
    if PEXELS:
        js = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": PEXELS},
                          params={"query": query, "orientation": "portrait", "size": "medium", "per_page": 8}, timeout=30).json()
        for v in js.get("videos", []):
            for vf in sorted(v.get("video_files", []), key=lambda x: x.get("height") or 0):
                if vf.get("file_type") == "video/mp4" and (vf.get("height") or 0) >= 1280:
                    return vf["link"]
    return None


def tts_fast(text, path):
    import asyncio
    import edge_tts
    asyncio.run(edge_tts.Communicate(text, mr.VOICE, rate="+15%").save(path))


def overlay_png(text, path):
    """무료 영상 위에 얹을 투명 글자판(가운데 위쪽 큰 자막 + 광고 표시)."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = mc.font("black", 92)
    lines = mc.wrap(d, mc.noemo(text), f, W - 160)
    y = 360
    for ln in lines:
        tw = d.textlength(ln, font=f)
        x = (W - tw) / 2
        d.rounded_rectangle([x - 28, y - 10, x + tw + 28, y + f.size + 26], radius=26, fill=(0, 0, 0, 170))
        d.text((x, y), ln, font=f, fill=(255, 230, 80))
        y += int(f.size * 1.35)
    fb = mc.font("bold", 30)
    tw = d.textlength(AD, font=fb)
    d.rounded_rectangle([40, 70, 40 + tw + 44, 126], radius=28, fill=(0, 0, 0, 220))
    d.text((62, 78), AD, font=fb, fill=(255, 255, 255))
    img.save(path)


def stock_clip(query, text, work, idx):
    """Pexels 무료 영상(세로) 한 컷 + 큰 자막 + 음성. 키가 없거나 실패하면 None."""
    if not (PEXELS or PIXABAY):
        return None
    try:
        link = stock_url(query)
        if not link:
            print(f"[꿀템] 무료 영상 없음: {query}")
            return None
        raw = os.path.join(work, f"s{idx}.mp4")
        open(raw, "wb").write(requests.get(link, timeout=60).content)
        ov = os.path.join(work, f"s{idx}.png")
        overlay_png(text, ov)
        a = os.path.join(work, f"s{idx}.mp3")
        tts_fast(mc.noemo(text), a)
        dur = min(5.5, max(3.5, mr.dur(a) + 0.6))
        c = os.path.join(work, f"sc{idx}.mp4")
        mr.run(["ffmpeg", "-y", "-i", raw, "-i", ov, "-i", a, "-filter_complex",
                f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps=30,setsar=1[v];[v][1:v]overlay=0:0,format=yuv420p[o]",
                "-map", "[o]", "-map", "2:a", "-af", "apad", "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-ar", "44100", c])
        print(f"[꿀템] 무료 영상 컷: {query} ({dur:.1f}초)")
        return c
    except Exception as e:  # noqa: BLE001
        print(f"[꿀템] 무료 영상 실패({query}): {e}")
        return None


def build_video(spec, prod, no, work, out):
    os.makedirs(work, exist_ok=True)
    photo = Image.open(io.BytesIO(requests.get(prod["image"], timeout=30).content)).convert("RGB")
    sn = short_name(prod["name"], 18)
    frames = [(frame_hook(photo, spec["hook"]), spec["hook"])]
    for i, p in enumerate(spec["points"][:3], 1):
        frames.append((frame_point(photo, i, p), p))
    say = f"오늘 골라 본 건 {sn}이에요. " + (f"가격은 {price_word(prod['price'])}. " if prod["price"] else "") + \
          f"링크는 프로필에서 {no}번을 눌러 주세요."
    frames.append((frame_product(photo, prod, no), say))
    frames.append((frame_cta(photo, spec.get("closing")), (spec.get("closing") or "") + " 저장해 두시고, 팔로우도 부탁드려요."))
    clips = []
    for j, sc in enumerate((spec.get("clips") or [])[:3]):  # 앞부분: 고민·공감 짤(이야기처럼 이어서)
        c = stock_clip(sc.get("query", ""), sc.get("text", ""), work, j)
        if c:
            clips.append(c)
    if clips:  # 짤(고민) 다음 '그래서 준비했다!'로 상품 장면에 이어 붙인다
        bridge = spec.get("bridge") or "그래서 준비했다!"
        frames = [(frame_bridge(photo, bridge), bridge)] + frames[1:]
    for i, (im, text) in enumerate(frames):
        f = os.path.join(work, f"f{i}.png")
        im.save(f)
        a = os.path.join(work, f"a{i}.mp3")
        tts_fast(mc.noemo(text), a)
        dur = max(2.0, mr.dur(a) + 0.25)
        n = int(dur * 30)
        c = os.path.join(work, f"c{i}.mp4")
        mr.run(["ffmpeg", "-y", "-loop", "1", "-i", f, "-i", a,
                "-vf", f"scale=2160:-1,zoompan=z='min(zoom+0.0012,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps=30,format=yuv420p",
                "-af", "apad", "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k", "-ar", "44100", c])
        clips.append(c)
    lst = os.path.join(work, "list.txt")
    open(lst, "w").writelines(f"file '{c}'\n" for c in clips)
    mr.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out])
    return mr.dur(out)


# ── 링크 모음 페이지 ─────────────────────────
def write_page(items):
    rows = "".join(
        f'<a class="it" href="{html.escape(x["link"])}" rel="nofollow sponsored noopener" target="_blank">'
        f'<span class="no">{x["no"]}</span><img src="{html.escape(x["image"])}" alt="" loading="lazy">'
        f'<span class="nm">{html.escape(short_name(x["name"], 40))}<small>{html.escape(x["date"])}</small></span></a>'
        for x in sorted(items, key=lambda x: -x["no"])[:60])
    page = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>생활 꿀템 모음</title><style>
:root{{--bg:#fff8f0;--card:#fff;--ink:#1e1e22;--sub:#777;--acc:#ff6b35}}
@media (prefers-color-scheme:dark){{:root{{--bg:#17171a;--card:#232328;--ink:#f2f2f4;--sub:#aaa;--acc:#ff8a5c}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:17px/1.5 -apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif}}
main{{max-width:560px;margin:0 auto;padding:20px 16px 40px}}h1{{font-size:24px;margin:6px 0}}
.ad{{background:#000;color:#fff;border-radius:12px;padding:10px 14px;font-size:14px;margin:10px 0 18px}}
.it{{display:flex;gap:12px;align-items:center;background:var(--card);border-radius:16px;padding:10px;margin-bottom:10px;color:inherit;text-decoration:none;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.no{{flex:none;width:52px;height:52px;border-radius:14px;background:var(--acc);color:#fff;font-weight:900;font-size:24px;display:grid;place-items:center}}
.it img{{width:64px;height:64px;object-fit:contain;background:#fff;border-radius:10px;flex:none}}
.nm{{font-weight:700;display:flex;flex-direction:column}}.nm small{{color:var(--sub);font-weight:400}}
</style></head><body><main><h1>🛒 생활 꿀템 모음</h1>
<p style="color:var(--sub);margin:0">영상에서 본 번호를 눌러 주세요 · {HANDLE}</p>
<div class="ad">{html.escape(DISCLOSURE)} 가격·재고는 바뀔 수 있어요.</div>{rows}</main></body></html>"""
    os.makedirs(os.path.dirname(PAGE), exist_ok=True)
    open(PAGE, "w", encoding="utf-8").write(page)


def caption(spec, prod, no):
    tags = " ".join(dict.fromkeys((spec.get("tags") or [])[:10] + ["#생활꿀템", "#살림템", "#쿠팡추천템"]))
    return (f"{DISCLOSURE}\n\n{spec.get('caption', '').strip()}\n\n"
            f"🛒 오늘의 꿀템: {short_name(prod['name'], 40)}\n👉 구매 링크: 프로필 링크 → {no}번\n"
            f"(가격·재고는 바뀔 수 있어요)\n\n저장해 두고 필요할 때 꺼내 보세요 📌\n\n{tags}")[:2100]


def publish(url, cap):
    cid = pr.call("POST", f"{pr.IG_ID}/media", media_type="REELS", video_url=url, caption=cap, share_to_feed="true")["id"]
    end = time.time() + 600
    while time.time() < end:
        st = pr.call("GET", cid, fields="status_code").get("status_code")
        if st == "FINISHED":
            break
        if st in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"컨테이너 {st}")
        time.sleep(8)
    for i in range(4):
        try:
            return pr.call("POST", f"{pr.IG_ID}/media_publish", creation_id=cid)["id"]
        except RuntimeError as e:
            print(f"[꿀템] 게시 재시도 {i + 1}: {e}")
            time.sleep(20)
            for m in pr.call("GET", f"{pr.IG_ID}/media", fields="id,caption", limit="3").get("data", []):
                if (m.get("caption") or "")[:80] == cap[:80]:
                    return m["id"]
    raise RuntimeError("릴스 게시 실패")


def push(msg, *paths):
    pr.git("config", "user.name", "blog-bot")
    pr.git("config", "user.email", "blog-bot@users.noreply.github.com")
    pr.git("add", *paths)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        return
    pr.git("commit", "-qm", msg)
    for _ in range(3):
        try:
            pr.git("pull", "--rebase", "-q", "origin", "main")
            pr.git("push", "-q", "origin", "HEAD:main")
            return
        except subprocess.CalledProcessError:
            time.sleep(5)


def main():
    files = sorted(glob.glob(os.path.join(Q, "*.json")))
    if not files:
        print("[꿀템] 대기 대본 없음")
        return 0
    dry = os.environ.get("DRY") == "1"
    f = files[0]
    name = os.path.splitext(os.path.basename(f))[0]
    spec = json.load(open(f, encoding="utf-8"))
    log = load_log()
    if not dry and any(x.get("date") == kst().strftime("%m/%d") for x in log["items"]):
        print("[꿀템] 오늘은 이미 올림 — 내일 올림")
        return 0
    prod = pick(spec["search"], {x["id"] for x in log["items"]})
    if not prod:
        raise RuntimeError("검색어로 맞는 상품을 못 찾음")
    no = max([x["no"] for x in log["items"]] or [0]) + 1
    out = os.path.join(ROOT, "instagram", "media", "products", f"{name}.mp4")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    secs = build_video(spec, prod, no, os.path.join("/tmp", "pr_" + name), out)
    print(f"[꿀템] 영상 {secs:.1f}초")
    cap = caption(spec, prod, no)
    if dry:
        prev = os.path.join(ROOT, "instagram", "media", "products", "preview.mp4")
        shutil.copy(out, prev)
        push("인스타 꿀템 미리보기 영상 [skip ci]", prev)
        print("[꿀템] 시험 실행 — 게시 안 함\n" + cap)
        return 0
    item = {"no": no, "id": prod["id"], "name": prod["name"], "link": prod["link"], "image": prod["image"],
            "price": prod["price"], "date": kst().strftime("%m/%d"), "file": name}
    log["items"].append(item)
    write_page(log["items"])
    push(f"인스타 꿀템 영상·링크 {name} [skip ci]", out, PAGE)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    rel = os.path.relpath(out, ROOT)
    time.sleep(10)
    mid = publish(f"https://raw.githubusercontent.com/{pr.REPO}/{sha}/{rel}", cap)
    try:
        item["permalink"] = pr.call("GET", mid, fields="permalink").get("permalink", "")
    except RuntimeError:
        pass
    item["ig_media_id"] = mid
    json.dump(log, open(LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.makedirs(DONE, exist_ok=True)
    shutil.move(f, os.path.join(DONE, os.path.basename(f)))
    push("인스타 꿀템 게시 기록 [skip ci]", LOG, Q, DONE)
    print(f"[꿀템] 게시 완료 {no}번 {item.get('permalink', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
