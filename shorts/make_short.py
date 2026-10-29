# -*- coding: utf-8 -*-
"""쇼츠 영상 자동 제작기 (무료 도구만 사용).

shorts/queue/*.json 대본을 읽어
  1) 장면마다 무료 AI 음성(edge-tts)으로 내레이션을 만들고
  2) 무료 AI 이미지(pollinations)로 배경을 만들고 (실패하면 그라데이션 배경)
  3) 큰 자막·상단 제목을 얹어 9:16 세로 영상(1080x1920)으로 합친 뒤
  4) 텔레그램으로 영상과 제목·설명·태그를 보낸다.
처리한 대본은 shorts/done/ 으로 옮긴다.

대본 형식(JSON):
{
  "title": "유튜브 제목",
  "hook": "영상 상단에 계속 떠 있을 짧은 문구(14자 이내 권장)",
  "voice": "ko-KR-SunHiNeural" (여성) 또는 "ko-KR-InJoonNeural" (남성),
  "scenes": [{"text": "내레이션 겸 자막 한두 문장", "image": "english image prompt"}],
  "description": "유튜브 설명란",
  "tags": ["#태그", ...],
  "pinned_comment": "고정 댓글(선택)"
}
"""
import asyncio
import glob
import json
import os
import random
import re
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.parse

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(ROOT, "queue")
DONE = os.path.join(ROOT, "done")
WORK = os.path.join(ROOT, "_work")
OUT = os.path.join(ROOT, "_out")
W, H, FPS = 1080, 1920, 30

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            # .ttc 안에서 KR 글꼴 인덱스를 찾는다
            for idx in range(10):
                try:
                    f = ImageFont.truetype(path, size, index=idx)
                    if "KR" in " ".join(f.getname()):
                        return f
                except Exception:  # noqa: BLE001
                    break
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"명령 실패: {' '.join(cmd[:6])}...\n{p.stderr[-1500:]}")
    return p.stdout


def duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    return float(out.strip())


# ---------------------------------------------------------------- 음성

async def _tts(text, voice, path):
    import edge_tts
    com = edge_tts.Communicate(text, voice, rate="+8%")
    await com.save(path)


def tts(text, voice, path):
    for attempt in range(3):
        try:
            asyncio.run(_tts(text, voice, path))
            if os.path.getsize(path) > 1000:
                return
        except Exception as e:  # noqa: BLE001
            print(f"[음성] 재시도 {attempt + 1}: {e}")
            time.sleep(3)
    raise RuntimeError("음성 생성 실패")


# ---------------------------------------------------------------- 이미지

STYLE = ("cinematic, warm soft light, emotional, photorealistic, Korean people, "
         "vertical composition, high detail, no text, no watermark")


def _save_if_image(content, path):
    if len(content) < 20000:
        return False
    with open(path, "wb") as f:
        f.write(content)
    try:
        Image.open(path).verify()
        return True
    except Exception:  # noqa: BLE001
        return False


CREDITS = []
IMG_LOG = []
UA = {"User-Agent": "BaramShortsBot/1.0 (https://baram-salim.blogspot.com; shorts maker)"}
OK_LICENSE = ("public domain", "pd", "cc0", "cc by", "cc-by")


def commons_image(query, path, seed):
    """위키미디어 공용 무료 사진 (퍼블릭 도메인/CC0 우선, CC BY 계열은 출처를 설명란에 표기)."""
    words = [w for w in query.replace(",", " ").split() if len(w) > 2]
    started = time.time()
    for q in (" ".join(words[:3]), " ".join(words[:2]), words[0] if words else ""):
        if not q or time.time() - started > 30:
            continue
        try:
            r = requests.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=15, params={
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": f"filetype:bitmap {q}", "gsrnamespace": 6, "gsrlimit": 20,
                "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1200})
            pages = list((r.json().get("query") or {}).get("pages", {}).values()) if r.ok else []
        except Exception as e:  # noqa: BLE001
            print(f"[이미지] Commons 오류: {e}")
            continue
        cands = []
        for pg in pages:
            ii = (pg.get("imageinfo") or [{}])[0]
            meta = ii.get("extmetadata") or {}
            lic = (meta.get("LicenseShortName", {}).get("value") or "").lower()
            if not any(k in lic for k in OK_LICENSE) or "nc" in lic or "nd" in lic:
                continue
            if (ii.get("width") or 0) < 800 or not ii.get("thumburl"):
                continue
            artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value") or "").strip()[:60]
            pd_first = 0 if ("public" in lic or "cc0" in lic or lic == "pd") else 1
            tall = -(ii.get("height") or 1) / max(1, ii.get("width") or 1)
            cands.append((pd_first, tall, ii["thumburl"], lic, artist, pg.get("title", "")))
        cands.sort()
        rnd = random.Random(seed)
        top = cands[:5]
        rnd.shuffle(top)
        for _, _, url, lic, artist, title in top[:3]:
            try:
                img = requests.get(url, headers=UA, timeout=15)
                if img.ok and _save_if_image(img.content, path):
                    print(f"[이미지] Commons: {q} ({lic})")
                    if "public" not in lic and "cc0" not in lic and lic != "pd":
                        CREDITS.append(f"{title.replace('File:', '')} / {artist or 'Wikimedia Commons'} / {lic.upper()}")
                    return True
            except Exception:  # noqa: BLE001
                continue
    return False


def openverse_image(query, path, seed):
    """Openverse 무료 사진(CC0·퍼블릭 도메인만 — 출처 표기 의무 없음)."""
    words = [w for w in query.replace(",", " ").split() if len(w) > 2][:6]
    started = time.time()
    for q in (" ".join(words[:4]), " ".join(words[:2])):
        if time.time() - started > 25:
            break
        if not q:
            continue
        try:
            r = requests.get("https://api.openverse.org/v1/images/",
                             params={"q": q, "license": "cc0,pdm", "page_size": 20, "mature": "false"},
                             headers={"User-Agent": "shorts-bot/1.0"}, timeout=6)
            results = r.json().get("results", []) if r.ok else []
        except Exception as e:  # noqa: BLE001
            print(f"[이미지] Openverse 오류: {e}")
            results = []
        # 세로로 긴 사진·큰 사진을 우선
        results.sort(key=lambda x: (-(x.get("height") or 0) / max(1, (x.get("width") or 1)),
                                    -(x.get("width") or 0)))
        rnd = random.Random(seed)
        pool = results[:6]
        rnd.shuffle(pool)
        for item in pool[:3]:
            if time.time() - started > 25:
                break
            url = item.get("url")
            if not url or (item.get("width") or 0) < 600:
                continue
            try:
                img = requests.get(url, timeout=12, headers={"User-Agent": "shorts-bot/1.0"})
                if img.ok and _save_if_image(img.content, path):
                    print(f"[이미지] Openverse: {q} ({item.get('license')})")
                    return True
            except Exception:  # noqa: BLE001
                continue
    return False


_POLLI_OK = [True]


def cloudflare_image(prompt, path, seed):
    """Cloudflare Workers AI (무료 하루 1만 뉴런 ≈ 사진 150장) — 장면에 딱 맞는 AI 사진."""
    acc = os.environ.get("CF_ACCOUNT_ID", "").strip()
    tok = os.environ.get("CF_API_TOKEN", "").strip()
    if not (acc and tok):
        IMG_LOG.append(f"CF키없음 acc={bool(acc)} tok={bool(tok)}")
        return False
    try:
        r = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/@cf/black-forest-labs/flux-1-schnell",
            headers={"Authorization": f"Bearer {tok}"},
            json={"prompt": prompt, "steps": 6},
            timeout=90)
        img = (r.json().get("result") or {}).get("image") if r.ok else None
        if img:
            import base64
            with open(path, "wb") as f:
                f.write(base64.b64decode(img))
            Image.open(path).verify()
            print("[이미지] Cloudflare AI")
            IMG_LOG.append("AI")
            return True
        print(f"[이미지] Cloudflare 응답 {r.status_code}: {r.text[:200]}")
        IMG_LOG.append(f"CF실패 {r.status_code}: {r.text[:300]}")
    except Exception as e:  # noqa: BLE001
        print(f"[이미지] Cloudflare 오류: {e}")
        IMG_LOG.append(f"CF오류: {e}")
    return False


def fetch_image(prompt, path, seed, commons_query=None):
    # 0순위: Cloudflare AI (키가 있을 때)
    if cloudflare_image(prompt, path, seed):
        return True
    # 1순위: Pollinations AI 이미지 (한 번 막히면 이번 영상에선 다시 시도하지 않음)
    if not _POLLI_OK[0]:
        return commons_image(commons_query or prompt, path, seed) or openverse_image(commons_query or prompt, path, seed)
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt)
           + f"?width={W}&height={H}&nologo=true&seed={seed}")
    try:
        r = requests.get(url, timeout=45)
        if r.status_code == 200 and _save_if_image(r.content, path):
            print("[이미지] Pollinations AI")
            return True
        print(f"[이미지] Pollinations 응답 {r.status_code} → 무료 사진으로 대체")
        if r.status_code in (401, 402, 403, 429):
            _POLLI_OK[0] = False
    except Exception as e:  # noqa: BLE001
        print(f"[이미지] Pollinations 오류: {e}")
        _POLLI_OK[0] = False
    # 2순위: 위키미디어 공용 무료 사진, 3순위: Openverse
    q = commons_query or prompt
    return commons_image(q, path, seed) or openverse_image(q, path, seed)


def gradient_bg(path, seed):
    rnd = random.Random(seed)
    palettes = [((24, 32, 58), (88, 62, 92)), ((30, 44, 52), (120, 92, 60)),
                ((40, 28, 36), (140, 96, 80)), ((20, 40, 60), (70, 110, 130))]
    a, b = rnd.choice(palettes)
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)))
    for _ in range(6):
        r = rnd.randint(120, 380)
        x, y = rnd.randint(0, W), rnd.randint(0, H)
        d.ellipse([x - r, y - r, x + r, y + r], fill=tuple(min(255, c + 25) for c in b))
    img.filter(ImageFilter.GaussianBlur(60)).save(path)


def prepare_image(src, dst):
    img = Image.open(src).convert("RGB")
    # 세로 9:16 으로 꽉 차게 자르기
    scale = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
    left, top = (img.width - W) // 2, (img.height - H) // 2
    img = img.crop((left, top, left + W, top + H))
    img.save(dst, quality=92)


# ---------------------------------------------------------------- 자막 그림

def wrap_ko(text, width):
    lines = []
    for para in text.split("\n"):
        lines += textwrap.wrap(para, width=width, break_long_words=True) or [""]
    return lines


def overlay_png(hook, subtitle, path, outro=False):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 위·아래 어둡게(글씨가 잘 보이도록)
    for y in range(0, 420):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(170 * (1 - y / 420))))
    for y in range(H - 900, H):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(160 * (y - (H - 900)) / 900)))
    # 상단 제목(영상 내내 고정)
    f_hook = font(80)
    lines = wrap_ko(hook, 11)[:3]
    box_h = 70 + len(lines) * 108
    d.rounded_rectangle([50, 150, W - 50, 150 + box_h], radius=36, fill=(0, 0, 0, 150))
    y = 185
    for line in lines:
        tw = d.textlength(line, font=f_hook)
        d.text(((W - tw) / 2, y), line, font=f_hook, fill=(255, 226, 110),
               stroke_width=5, stroke_fill=(0, 0, 0))
        y += 108
    # 하단 자막 (반투명 상자 + 굵은 흰 글씨로 또렷하게)
    f_sub = font(72)
    lines = wrap_ko(subtitle, 13)[:4]
    total = len(lines) * 100
    top = H - 600 - total // 2
    d.rounded_rectangle([60, top - 40, W - 60, top + total + 30], radius=32, fill=(0, 0, 0, 165))
    y = top
    for line in lines:
        tw = d.textlength(line, font=f_sub)
        d.text(((W - tw) / 2, y), line, font=f_sub, fill=(255, 255, 255),
               stroke_width=4, stroke_fill=(0, 0, 0))
        y += 100
    if outro:
        f_b = font(70)
        for k, (label, color) in enumerate([("👍 좋아요", (255, 255, 255)), ("🔔 구독", (255, 255, 255))]):
            label = label.split(" ", 1)[1]
            bx = W // 2 - 400 + k * 420
            by = H // 2 - 120
            d.rounded_rectangle([bx, by, bx + 380, by + 140], radius=70,
                                fill=(230, 30, 40, 235) if k == 1 else (40, 40, 40, 220))
            tw = d.textlength(label, font=f_b)
            d.text((bx + (380 - tw) / 2, by + 28), label, font=f_b, fill=color)
    img.save(path)


# ---------------------------------------------------------------- 영상

SCENERY = [
    "golden sunset over calm sea", "misty mountains at dawn", "autumn maple leaves path in a park",
    "quiet countryside rice field at golden hour", "starry night sky over hills", "soft clouds in blue sky",
    "cherry blossom trees by a river", "snowy pine forest in winter", "calm lake reflection at sunrise",
    "old stone wall alley with warm street lights at night", "rain drops on a window with blurred city lights",
    "wildflower meadow under evening sky", "lighthouse by the sea at dusk", "bamboo forest with sunlight",
]
MOOD_SCENERY = [
    (r"아버지|어머니|엄마|아빠|부모|아들|딸|자식|가족|며느리|손주|형제|남편|아내|고향",
     ["warm sunset over a quiet Korean countryside village", "old traditional Korean house with tiled roof at dusk",
      "persimmon tree in autumn countryside", "country road lined with autumn trees at golden hour",
      "old wooden porch with warm lamp light at evening", "rice field at sunset with mountains behind",
      "falling autumn leaves in an old village alley", "starry night sky over a quiet village"]),
    (r"돈|통장|연금|저축|월급|재산|상속|노후|은퇴|빚|보험|집값|아파트",
     ["calm lake reflection at sunrise", "golden wheat field under soft clouds", "quiet city skyline at dawn",
      "sunrise over the sea horizon", "peaceful garden path in spring", "mountain trail with morning mist"]),
    (r"건강|병원|약|무릎|허리|혈압|당뇨|치매|잠|운동|음식",
     ["fresh green forest with morning sunlight", "calm sea waves on a sandy beach", "green tea field on hills",
      "clear mountain stream in a forest", "flower garden in spring morning", "walking path by a river in spring"]),
    (r"겨울|눈|추위|연말|설날|크리스마스",
     ["snowy pine forest in winter", "snow covered traditional village at night", "frosty winter morning field"]),
    (r"봄|벚꽃|꽃",
     ["cherry blossom trees by a river", "spring flower field under blue sky"]),
]
NO_PEOPLE = "beautiful landscape scenery, no people, no person, no text, cinematic, soft light, high detail, vertical"


def pick_scenery(script, i, seed):
    title = script.get("title", "") + " " + script.get("hook", "")
    for pat, options in MOOD_SCENERY:
        if re.search(pat, title):
            return options[(seed + i) % len(options)]
    return SCENERY[(seed + i) % len(SCENERY)]


def clean_title(t):
    return re.sub(r"\s*#\S+", "", t or "").strip()


def make_scene(i, scene, voice, hook, base_seed, script=None):
    audio = os.path.join(WORK, f"a{i}.mp3")
    raw = os.path.join(WORK, f"raw{i}.jpg")
    bg = os.path.join(WORK, f"bg{i}.jpg")
    ov = os.path.join(WORK, f"ov{i}.png")
    clip = os.path.join(WORK, f"c{i:02d}.mp4")
    tts(scene["text"], voice, audio)
    scenery = scene.get("bg") or pick_scenery(script or {}, i, base_seed)
    if os.path.exists(raw):
        pass  # 미리 받아 둔 사진
    elif not fetch_image(f"{scenery}, {NO_PEOPLE}", raw, base_seed + i, commons_query=scenery):
        print(f"[이미지] 장면 {i}: 그라데이션 배경으로 대체")
        gradient_bg(raw, base_seed + i)
    prepare_image(raw, bg)
    overlay_png(hook, scene["text"], ov, outro=scene.get("outro", False))
    dur = duration(audio) + 0.35
    frames = int(dur * FPS) + 1
    zoom_in = i % 2 == 0
    z = "min(1+0.0009*on,1.12)" if zoom_in else "max(1.12-0.0009*on,1.0)"
    vf = (f"[0:v]scale={int(W * 1.12)}:{int(H * 1.12)},"
          f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS}[bg];"
          f"[bg][1:v]overlay=0:0,format=yuv420p[v]")
    run(["ffmpeg", "-y", "-loop", "1", "-i", bg, "-i", ov, "-i", audio,
         "-filter_complex", vf, "-map", "[v]", "-map", "2:a",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
         "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
         "-t", f"{dur:.2f}", "-r", str(FPS), clip])
    return clip


def build_video(script, out_path):
    CREDITS.clear()
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)
    voice = script.get("voice") or "ko-KR-SunHiNeural"
    hook = clean_title(script["title"]) or script.get("hook", "")
    seed = random.randint(1, 10_000_000)
    scenes = list(script["scenes"])
    # 마지막에 구독·좋아요 인사 장면
    outro = script.get("outro") or "오늘 이야기가 마음에 닿으셨다면, 구독과 좋아요 꼭 부탁드려요."
    scenes.append({"text": outro, "bg": "warm sunset sky with soft clouds over calm hills", "outro": True})
    # 사진을 한꺼번에 미리 받아 두기(빠르게)
    from concurrent.futures import ThreadPoolExecutor

    def _pre(i_s):
        i, sc = i_s
        scenery = sc.get("bg") or pick_scenery(script, i, seed)
        raw = os.path.join(WORK, f"raw{i}.jpg")
        try:
            fetch_image(f"{scenery}, {NO_PEOPLE}", raw, seed + i, commons_query=scenery)
        except Exception as e:  # noqa: BLE001
            print(f"[이미지] 미리받기 실패 {i}: {e}")
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(_pre, enumerate(scenes)))
    clips = [make_scene(i, s, voice, hook, seed, script) for i, s in enumerate(scenes)]
    listfile = os.path.join(WORK, "list.txt")
    with open(listfile, "w") as f:
        f.writelines(f"file '{c}'\n" for c in clips)
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
         "-c", "copy", "-movflags", "+faststart", out_path])
    return duration(out_path)


# ---------------------------------------------------------------- 텔레그램

CHAT_FILE = os.path.join(os.path.dirname(ROOT), "data", "shorts_chat_id.txt")


def bot_token():
    return (os.environ.get("SHORTS_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()


def chat_id():
    """채팅방 번호: 비밀값 → 저장된 파일 → 봇에게 온 최근 메시지 순서로 찾는다."""
    cid = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if cid:
        return cid
    if os.path.exists(CHAT_FILE):
        cid = open(CHAT_FILE).read().strip()
        if cid:
            return cid
    res = tg("getUpdates", data={"limit": 100, "allowed_updates": json.dumps(["message", "my_chat_member"])})
    me = tg("getMe").get("result", {})
    print(f"[텔레그램] 봇 @{me.get('username')} / 받은 메시지 {len(res.get('result', []))}개")
    for upd in reversed(res.get("result", [])):
        msg = upd.get("message") or upd.get("my_chat_member") or {}
        chat = msg.get("chat") or {}
        if chat.get("type") == "private" and chat.get("id"):
            cid = str(chat["id"])
            os.makedirs(os.path.dirname(CHAT_FILE), exist_ok=True)
            open(CHAT_FILE, "w").write(cid + "\n")
            return cid
    raise RuntimeError("텔레그램 채팅방을 못 찾음: 쇼츠 봇에게 /start 메시지를 먼저 보내 주세요")


def tg(method, data=None, files=None):
    token = bot_token()
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}", data=data, files=files, timeout=300)
    if not r.ok:
        raise RuntimeError(f"텔레그램 실패 {r.status_code}: {r.text[:300]}")
    return r.json()


COUPANG_FILE = os.path.join(os.path.dirname(ROOT), "data", "shorts_coupang.txt")
DISCLOSURE = "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."


def pick_coupang(script):
    """대본의 coupang.keywords 와 가장 잘 맞는 쿠팡 파트너스 링크 1개를 고른다.
    data/shorts_coupang.txt 형식: 단축링크 | 상품명 | 키워드1,키워드2,..."""
    want = script.get("coupang") or {}
    keys = [k.strip() for k in want.get("keywords", []) if k.strip()]
    if not os.path.exists(COUPANG_FILE):
        return None, want
    rows = []
    for line in open(COUPANG_FILE, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [x.strip() for x in line.split("|")]
        if len(parts) >= 2 and parts[0].startswith("http"):
            rows.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    if not rows:
        return None, want
    exact = (want.get("url") or "").strip()
    for r in rows:
        if exact and r[0] == exact:
            return r, want
    def score(row):
        hay = row[1] + " " + row[2]
        return sum(3 if k in row[2] else 1 for k in keys if k in hay)
    best = max(rows, key=score)
    if score(best) == 0:
        best = random.choice(rows)
    return best, want


YT_TITLE_MAX = 100


def yt_clean(text):
    return (text or "").replace("<", "〈").replace(">", "〉")


def yt_access_token():
    rt = os.environ.get("YOUTUBE_REFRESH_TOKEN", "").strip()
    if not rt:
        return ""
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": os.environ.get("YT_CLIENT_ID", "").strip() or os.environ.get("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.environ.get("YT_CLIENT_SECRET", "").strip() or os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        "refresh_token": rt, "grant_type": "refresh_token"}, timeout=30)
    tok = r.json().get("access_token")
    if not tok:
        raise RuntimeError(f"유튜브 연결 토큰 오류: {r.text[:300]}")
    return tok


def yt_upload(video, title, desc, tags, privacy=None, shorts=True):
    """유튜브에 바로 올림. 구글 심사 전에는 유튜브가 자동으로 비공개 처리함."""
    tok = yt_access_token()
    if not tok:
        return None
    title = yt_clean(title)
    if shorts and "#shorts" not in title.lower() and len(title) + 8 <= YT_TITLE_MAX:
        title += " #shorts"
    clean_tags, total = [], 0
    for t in tags:
        t = yt_clean(t.lstrip("#")).strip()
        if t and total + len(t) + 2 < 450:
            clean_tags.append(t)
            total += len(t) + 2
    meta = {
        "snippet": {"title": title[:YT_TITLE_MAX], "description": yt_clean(desc)[:4900],
                    "tags": clean_tags, "categoryId": "22",
                    "defaultLanguage": "ko", "defaultAudioLanguage": "ko"},
        "status": {"privacyStatus": privacy or os.environ.get("YT_PRIVACY", "public"),
                   "selfDeclaredMadeForKids": False},
    }
    size = os.path.getsize(video)
    r = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
        data=json.dumps(meta), timeout=60)
    if r.status_code >= 300 or "Location" not in r.headers:
        raise RuntimeError(f"유튜브 업로드 시작 실패 {r.status_code}: {r.text[:300]}")
    with open(video, "rb") as f:
        up = requests.put(r.headers["Location"], data=f,
                          headers={"Authorization": f"Bearer {tok}", "Content-Type": "video/mp4"},
                          timeout=600)
    if up.status_code >= 300:
        raise RuntimeError(f"유튜브 업로드 실패 {up.status_code}: {up.text[:300]}")
    info = up.json()
    return info.get("id"), info.get("status", {}).get("privacyStatus", "")


def build_texts(script):
    product, want = pick_coupang(script)
    desc = script.get("description", "")
    if CREDITS:
        desc += "\n\n📷 사진 출처(위키미디어 공용):\n" + "\n".join(f"- {c}" for c in CREDITS[:8])
    blog_lines = []
    if "dundeun-nohu" not in desc:
        blog_lines.append("📖 노후·연금·상속 정보 블로그: https://dundeun-nohu.blogspot.com")
    if "baram-salim" not in desc:
        blog_lines.append("💰 생활·경제·지원금 블로그: https://baram-salim.blogspot.com")
    if blog_lines:
        desc += "\n\n" + "\n".join(blog_lines)
    if product:
        desc = f"{DISCLOSURE}\n\n{desc}\n\n🛒 {product[1]}\n{product[0]}"
    return desc, product, want


def send(script, video, secs):
    chat = chat_id()
    tags = " ".join(script.get("tags", []))
    desc, product, want = build_texts(script)

    yt, yt_err = None, ""
    try:
        yt = yt_upload(video, script["title"], desc, script.get("tags", []), script.get("privacy"))
    except Exception as e:  # noqa: BLE001
        yt_err = str(e)[:300]
        print(f"[유튜브] {yt_err}")

    markup = None
    if yt:
        vid, privacy = yt
        studio = f"https://studio.youtube.com/video/{vid}/edit"
        if privacy == "public":
            head = "✅ 유튜브 쇼츠에 공개로 올라갔어요!"
            buttons = [[{"text": "▶ 쇼츠 보기", "url": f"https://youtube.com/shorts/{vid}"}],
                       [{"text": "✏️ 스튜디오에서 수정", "url": studio}]]
        else:
            head = ("✅ 유튜브에 올려 두었어요 (지금은 비공개)\n"
                    "👇 [게시하기] → 공개 상태 → '공개' → 저장 하면 끝!")
            buttons = [[{"text": "📤 게시하기 (공개로 바꾸기)", "url": studio}],
                       [{"text": "▶ 미리 보기", "url": f"https://youtube.com/shorts/{vid}"}]]
        markup = json.dumps({"inline_keyboard": buttons})
    elif yt_err:
        head = f"⚠️ 유튜브 자동 업로드 실패 — 직접 올려 주세요\n({yt_err[:150]})"
    else:
        head = "👇 아래 메시지의 설명·태그를 복사해서 유튜브 앱으로 올려 주세요."
    ai_n = sum(1 for x in IMG_LOG if x == "AI")
    caption = f"🎬 오늘의 쇼츠 ({secs:.0f}초) · AI사진 {ai_n}장\n\n📌 {script['title']}\n\n{head}"
    try:
        with open(os.path.join(os.path.dirname(ROOT), "data", "shorts_img_log.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(IMG_LOG))
    except Exception:  # noqa: BLE001
        pass
    data = {"chat_id": chat, "caption": caption[:1000], "supports_streaming": "true"}
    if markup:
        data["reply_markup"] = markup
    with open(video, "rb") as f:
        tg("sendVideo", data=data, files={"video": (os.path.basename(video), f, "video/mp4")})

    text = f"[제목]\n{script['title']}\n\n[설명]\n{desc}\n\n[태그]\n{tags}"
    if script.get("pinned_comment"):
        text += f"\n\n[고정 댓글] (공개 후 댓글로 달고 고정해 주세요)\n{script['pinned_comment']}"
    if product:
        text += f"\n\n[쿠팡 상품]\n🛒 {product[1]}\n{product[0]}"
        if want.get("reason"):
            text += f"\n(고른 이유: {want['reason']})"
    elif want.get("keywords"):
        text += f"\n\n[쿠팡 추천 검색어]\n{', '.join(want['keywords'])}"
    if not yt:
        text += ("\n\n[업로드 체크]\n✅ 유튜브 앱 → + → 동영상 업로드 → 이 영상 선택\n"
                 "✅ 쿠팡 링크를 넣었다면: 설정에서 '유료 프로모션 포함'에 체크")
    tg("sendMessage", data={"chat_id": chat, "text": text[:4000]})


def main():
    os.makedirs(DONE, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    files = sorted(glob.glob(os.path.join(QUEUE, "*.json")))
    if not files:
        print("대기 중인 쇼츠 대본 없음")
        return 0
    failed = 0
    for path in files:
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            script = json.load(open(path, encoding="utf-8"))
            video = os.path.join(OUT, f"{name}.mp4")
            secs = build_video(script, video)
            print(f"[완성] {name}: {secs:.1f}초")
            if not bot_token():
                raise RuntimeError("텔레그램 봇 토큰(SHORTS_BOT_TOKEN)이 GitHub 비밀값에 없음 — 영상은 Actions 보관함에만 있음")
            send(script, video, secs)
            print("[텔레그램] 전송 완료")
            shutil.move(path, os.path.join(DONE, os.path.basename(path)))
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[실패] {name}: {e}")
            try:
                tg("sendMessage", data={"chat_id": chat_id(),
                                        "text": f"[쇼츠] 제작 실패: {name}\n{str(e)[:500]}"})
            except Exception:  # noqa: BLE001
                pass
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
