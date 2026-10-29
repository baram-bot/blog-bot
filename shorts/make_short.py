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


def openverse_image(query, path, seed):
    """Openverse 무료 사진(CC0·퍼블릭 도메인만 — 출처 표기 의무 없음)."""
    words = [w for w in query.replace(",", " ").split() if len(w) > 2][:6]
    for q in (" ".join(words), " ".join(words[:3]), " ".join(words[:2])):
        if not q:
            continue
        try:
            r = requests.get("https://api.openverse.org/v1/images/",
                             params={"q": q, "license": "cc0,pdm", "page_size": 20, "mature": "false"},
                             headers={"User-Agent": "shorts-bot/1.0"}, timeout=40)
            results = r.json().get("results", []) if r.ok else []
        except Exception as e:  # noqa: BLE001
            print(f"[이미지] Openverse 오류: {e}")
            results = []
        # 세로로 긴 사진·큰 사진을 우선
        results.sort(key=lambda x: (-(x.get("height") or 0) / max(1, (x.get("width") or 1)),
                                    -(x.get("width") or 0)))
        rnd = random.Random(seed)
        pool = results[:8]
        rnd.shuffle(pool)
        for item in pool:
            url = item.get("url")
            if not url or (item.get("width") or 0) < 600:
                continue
            try:
                img = requests.get(url, timeout=40, headers={"User-Agent": "shorts-bot/1.0"})
                if img.ok and _save_if_image(img.content, path):
                    print(f"[이미지] Openverse: {q} ({item.get('license')})")
                    return True
            except Exception:  # noqa: BLE001
                continue
    return False


def fetch_image(prompt, path, seed):
    # 1순위: Pollinations AI 이미지 (무료가 막히면 바로 건너뜀)
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(f"{prompt}, {STYLE}")
           + f"?width={W}&height={H}&nologo=true&seed={seed}")
    try:
        r = requests.get(url, timeout=90)
        if r.status_code == 200 and _save_if_image(r.content, path):
            print("[이미지] Pollinations AI")
            return True
        print(f"[이미지] Pollinations 응답 {r.status_code} → 무료 사진으로 대체")
    except Exception as e:  # noqa: BLE001
        print(f"[이미지] Pollinations 오류: {e}")
    # 2순위: Openverse 무료 사진
    return openverse_image(prompt, path, seed)


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


def overlay_png(hook, subtitle, path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 위·아래 어둡게(글씨가 잘 보이도록)
    for y in range(0, 420):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(170 * (1 - y / 420))))
    for y in range(H - 900, H):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(190 * (y - (H - 900)) / 900)))
    # 상단 제목(고정)
    f_hook = font(76)
    lines = wrap_ko(hook, 13)[:2]
    y = 170
    for line in lines:
        tw = d.textlength(line, font=f_hook)
        d.text(((W - tw) / 2, y), line, font=f_hook, fill=(255, 230, 120),
               stroke_width=6, stroke_fill=(0, 0, 0))
        y += 100
    # 하단 자막
    f_sub = font(68)
    lines = wrap_ko(subtitle, 14)[:4]
    total = len(lines) * 92
    y = H - 560 - total // 2
    for line in lines:
        tw = d.textlength(line, font=f_sub)
        d.text(((W - tw) / 2, y), line, font=f_sub, fill=(255, 255, 255),
               stroke_width=6, stroke_fill=(0, 0, 0))
        y += 92
    img.save(path)


# ---------------------------------------------------------------- 영상

def make_scene(i, scene, voice, hook, base_seed):
    audio = os.path.join(WORK, f"a{i}.mp3")
    raw = os.path.join(WORK, f"raw{i}.jpg")
    bg = os.path.join(WORK, f"bg{i}.jpg")
    ov = os.path.join(WORK, f"ov{i}.png")
    clip = os.path.join(WORK, f"c{i:02d}.mp4")
    tts(scene["text"], voice, audio)
    if not fetch_image(scene.get("image") or scene["text"], raw, base_seed + i):
        print(f"[이미지] 장면 {i}: 그라데이션 배경으로 대체")
        gradient_bg(raw, base_seed + i)
    prepare_image(raw, bg)
    overlay_png(hook, scene["text"], ov)
    dur = duration(audio) + 0.35
    frames = int(dur * FPS) + 1
    zoom_in = i % 2 == 0
    z = "min(1+0.0009*on,1.12)" if zoom_in else "max(1.12-0.0009*on,1.0)"
    vf = (f"[0:v]scale={int(W * 1.12)}:{int(H * 1.12)},"
          f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS}[bg];"
          f"[bg][1:v]overlay=0:0,format=yuv420p[v]")
    run(["ffmpeg", "-y", "-loop", "1", "-i", bg, "-i", ov, "-i", audio,
         "-filter_complex", vf, "-map", "[v]", "-map", "2:a",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
         "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
         "-t", f"{dur:.2f}", "-r", str(FPS), clip])
    return clip


def build_video(script, out_path):
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)
    voice = script.get("voice") or "ko-KR-SunHiNeural"
    hook = script.get("hook") or script["title"][:14]
    seed = random.randint(1, 10_000_000)
    clips = [make_scene(i, s, voice, hook, seed) for i, s in enumerate(script["scenes"])]
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


def send(script, video, secs):
    chat = chat_id()
    tags = " ".join(script.get("tags", []))
    caption = (f"🎬 오늘의 쇼츠 ({secs:.0f}초)\n\n📌 제목\n{script['title']}\n\n"
               "👇 아래 메시지의 설명·태그를 복사해서 유튜브 앱으로 올려 주세요.")
    with open(video, "rb") as f:
        tg("sendVideo", data={"chat_id": chat, "caption": caption[:1000], "supports_streaming": "true"},
           files={"video": (os.path.basename(video), f, "video/mp4")})
    text = f"[제목]\n{script['title']}\n\n[설명]\n{script.get('description', '')}\n\n[태그]\n{tags}"
    if script.get("pinned_comment"):
        text += f"\n\n[고정 댓글]\n{script['pinned_comment']}"
    text += ("\n\n[업로드 체크]\n✅ 유튜브 앱 → + → 동영상 업로드 → 이 영상 선택\n"
             "✅ '변경되거나 합성된 콘텐츠' 질문: 사실적인 AI 이미지가 들어갔다면 '예'")
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
