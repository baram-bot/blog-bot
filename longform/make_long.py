# -*- coding: utf-8 -*-
"""롱폼(가로 16:9, 8~12분) 사연 영상 자동 제작 + 유튜브 업로드.

longform/queue/*.json 대본:
{"title": "...", "voice": "ko-KR-InJoonNeural",
 "chapters": [{"title": "1장. ...", "scenes": [{"text": "2~4문장", "bg": "영어 풍경"}]}],
 "description": "...", "tags": [...], "coupang": {"url": "...", "keywords": [...], "reason": "..."},
 "thumbnail_text": "썸네일 큰 글씨(12자 안팎)"}
"""
import glob
import json
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "shorts"))
import make_short as ms  # noqa: E402

ms.W, ms.H = 1920, 1080
W, H, FPS = 1920, 1080, 30
QUEUE = os.path.join(HERE, "queue")
DONE = os.path.join(HERE, "done")
WORK = os.path.join(HERE, "_work")
OUT = os.path.join(HERE, "_out")
NO_PEOPLE = "beautiful landscape scenery, no people, no person, no text, cinematic, soft warm light, high detail, wide shot"


# 인물별 목소리(무료 edge-tts 음성 + 높낮이·속도 조절)
VOICE_PRESETS = {
    "grandma": ("ko-KR-SunHiNeural", "-14%", "-20Hz", "할머니"),
    "grandpa": ("ko-KR-InJoonNeural", "-14%", "-16Hz", "할아버지"),
    "mother": ("ko-KR-SunHiNeural", "-5%", "-8Hz", "어머니"),
    "father": ("ko-KR-InJoonNeural", "-6%", "-9Hz", "아버지"),
    "young_man": ("ko-KR-HyunsuMultilingualNeural", "+6%", "+0Hz", "청년"),
    "young_woman": ("ko-KR-SunHiNeural", "+6%", "+10Hz", "젊은 여자"),
    "child": ("ko-KR-SunHiNeural", "+8%", "+32Hz", "아이"),
    "man": ("ko-KR-InJoonNeural", "+0%", "+0Hz", "남자"),
    "woman": ("ko-KR-SunHiNeural", "+0%", "+0Hz", "여자"),
}
FALLBACK = {"ko-KR-HyunsuMultilingualNeural": "ko-KR-InJoonNeural"}


async def _tts_v(text, voice, rate, pitch, path):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(path)


def tts_v(text, who, narrator, path):
    import asyncio
    voice, rate, pitch, _ = VOICE_PRESETS.get(who) or (narrator, "+8%", "+0Hz", "")
    for attempt in range(3):
        try:
            asyncio.run(_tts_v(text, voice, rate, pitch, path))
            if os.path.getsize(path) > 1000:
                return
        except Exception as e:  # noqa: BLE001
            print(f"[음성] {who} 재시도 {attempt + 1}: {e}")
            voice = FALLBACK.get(voice, voice)
    raise RuntimeError("음성 생성 실패")


def scene_lines(scene):
    """(누가, 문장) 목록. lines 가 있으면 인물별, 없으면 해설자."""
    out = []
    if scene.get("lines"):
        for ln in scene["lines"]:
            who = ln.get("who", "narrator")
            for s in sentences(ln.get("text", "")):
                out.append((who, s))
    else:
        for s in sentences(scene.get("text", "")):
            out.append(("narrator", s))
    return out


def sentences(text):
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if out and len(out[-1]) < 14:
            out[-1] += " " + p
        else:
            out.append(p)
    return out


def overlay(chapter, sub, path, channel="바람따라구름따라", speaker=""):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in range(H - 380, H):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(150 * (y - (H - 380)) / 380)))
    f_ch = ms.font(40)
    d.rounded_rectangle([40, 36, 60 + d.textlength(chapter, font=f_ch) + 30, 106], radius=20, fill=(0, 0, 0, 150))
    d.text((70, 46), chapter, font=f_ch, fill=(255, 226, 110))
    f_c = ms.font(30)
    tw = d.textlength(channel, font=f_c)
    d.text((W - tw - 50, 52), channel, font=f_c, fill=(255, 255, 255, 200))
    f = ms.font(62)
    lines = ms.wrap_ko(sub, 26)[:3]
    total = len(lines) * 84
    top = H - 110 - total
    width = max(d.textlength(l, font=f) for l in lines) if lines else 0
    d.rounded_rectangle([(W - width) / 2 - 40, top - 26, (W + width) / 2 + 40, top + total + 14], radius=28, fill=(0, 0, 0, 170))
    color = (255, 255, 255)
    if speaker:
        color = (255, 236, 170)
        f_sp = ms.font(40)
        sw = d.textlength(speaker, font=f_sp)
        d.rounded_rectangle([(W - sw) / 2 - 24, top - 92, (W + sw) / 2 + 24, top - 40], radius=24, fill=(150, 90, 40, 210))
        d.text(((W - sw) / 2, top - 88), speaker, font=f_sp, fill=(255, 255, 255))
    y = top
    for l in lines:
        lw = d.textlength(l, font=f)
        d.text(((W - lw) / 2, y), l, font=f, fill=color, stroke_width=3, stroke_fill=(0, 0, 0))
        y += 84
    img.save(path)


def make_scene(idx, chapter, scene, voice, seed):
    raw = os.path.join(WORK, f"raw{idx}.jpg")
    bg = os.path.join(WORK, f"bg{idx}.jpg")
    if not os.path.exists(raw):
        if not ms.fetch_image(f"{scene.get('bg','calm landscape')}, {NO_PEOPLE}", raw, seed + idx,
                              commons_query=scene.get("bg")):
            ms.gradient_bg(raw, seed + idx)
    ms.prepare_image(raw, bg)
    sents = scene_lines(scene)
    auds, ovs, durs = [], [], []
    for j, (who, s) in enumerate(sents):
        a = os.path.join(WORK, f"a{idx}_{j}.mp3")
        tts_v(s, who, voice, a)
        o = os.path.join(WORK, f"o{idx}_{j}.png")
        label = (VOICE_PRESETS.get(who) or ("", "", "", ""))[3]
        overlay(chapter, s, o, speaker=label)
        auds.append(a); ovs.append(o); durs.append(ms.duration(a) + 0.25)
    # 문장 음성 합치기
    lst = os.path.join(WORK, f"al{idx}.txt")
    with open(lst, "w") as fh:
        fh.writelines(f"file '{a}'\n" for a in auds)
    audio = os.path.join(WORK, f"scene{idx}.m4a")
    # 문장 사이 0.25초 쉼: apad 로 각 문장 끝에 여백
    inputs, filt = [], ""
    for k, a in enumerate(auds):
        inputs += ["-i", a]
        filt += f"[{k}:a]apad=pad_dur=0.25,aresample=44100,aformat=channel_layouts=stereo[x{k}];"
    filt += "".join(f"[x{k}]" for k in range(len(auds))) + f"concat=n={len(auds)}:v=0:a=1[a]"
    ms.run(["ffmpeg", "-y", *inputs, "-filter_complex", filt, "-map", "[a]", "-c:a", "aac", "-b:a", "160k", audio])
    total = sum(durs)
    frames = int(total * FPS) + 1
    z = "min(1+0.00025*on,1.10)" if idx % 2 == 0 else "max(1.10-0.00025*on,1.0)"
    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", bg]
    for o in ovs:
        cmd += ["-i", o]
    cmd += ["-i", audio]
    vf = (f"[0:v]scale={int(W*1.1)}:{int(H*1.1)},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
          f":d={frames}:s={W}x{H}:fps={FPS}[v0];")
    t = 0.0
    for k in range(len(ovs)):
        vf += f"[v{k}][{k+1}:v]overlay=0:0:enable='between(t,{t:.2f},{t+durs[k]:.2f})'[v{k+1}];"
        t += durs[k]
    vf += f"[v{len(ovs)}]format=yuv420p[v]"
    clip = os.path.join(WORK, f"c{idx:03d}.mp4")
    cmd += ["-filter_complex", vf, "-map", "[v]", "-map", f"{len(ovs)+1}:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "copy",
            "-t", f"{total:.2f}", "-r", str(FPS), clip]
    ms.run(cmd)
    return clip


def thumbnail(script, path):
    src = os.path.join(WORK, "bg0.jpg")
    img = Image.open(src).convert("RGB").resize((1280, 720))
    img = img.filter(ImageFilter.GaussianBlur(1))
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, 1280, 720], fill=(0, 0, 0, 90))
    text = script.get("thumbnail_text") or ms.clean_title(script["title"])
    f = ms.font(110)
    lines = ms.wrap_ko(text, 9)[:3]
    y = 360 - len(lines) * 70
    for l in lines:
        lw = d.textlength(l, font=f)
        d.text(((1280 - lw) / 2, y), l, font=f, fill=(255, 226, 90), stroke_width=8, stroke_fill=(0, 0, 0))
        y += 140
    img.save(path, quality=90)


def set_thumbnail(vid, path):
    try:
        tok = ms.yt_access_token()
        with open(path, "rb") as fh:
            r = ms.requests.post(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "image/jpeg"},
                                 data=fh.read(), timeout=60)
        print(f"[썸네일] {r.status_code} {r.text[:150]}")
        return r.ok
    except Exception as e:  # noqa: BLE001
        print(f"[썸네일] 실패: {e}")
        return False


def build(script, out):
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)
    ms.CREDITS.clear(); ms.IMG_LOG.clear()
    voice = script.get("voice") or "ko-KR-InJoonNeural"
    seed = ms.random.randint(1, 10_000_000)
    items = []
    for ch in script["chapters"]:
        for sc in ch["scenes"]:
            items.append((ch["title"], sc))
    items.append(("마무리", {"text": script.get("outro") or "오늘 이야기가 마음에 닿으셨다면 구독과 좋아요 부탁드립니다. 다음 이야기에서 또 뵙겠습니다.",
                             "bg": "warm sunset sky with soft clouds over calm hills"}))

    def pre(i_it):
        i, (_, sc) = i_it
        raw = os.path.join(WORK, f"raw{i}.jpg")
        try:
            ms.fetch_image(f"{sc.get('bg','calm landscape')}, {NO_PEOPLE}", raw, seed + i, commons_query=sc.get("bg"))
        except Exception as e:  # noqa: BLE001
            print(f"[이미지] {i}: {e}")
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(pre, enumerate(items)))
    clips = [make_scene(i, ch, sc, voice, seed) for i, (ch, sc) in enumerate(items)]
    lst = os.path.join(WORK, "list.txt")
    with open(lst, "w") as fh:
        fh.writelines(f"file '{c}'\n" for c in clips)
    ms.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out])
    return ms.duration(out)


def main():
    os.makedirs(DONE, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    files = sorted(glob.glob(os.path.join(QUEUE, "*.json")))
    if not files:
        print("대기 중인 롱폼 대본 없음")
        return 0
    failed = 0
    for path in files:
        name = os.path.splitext(os.path.basename(path))[0]
        if os.path.exists(os.path.join(DONE, os.path.basename(path))):
            print(f"[건너뜀] {name}: 이미 처리된 대본")
            os.remove(path)
            continue
        try:
            script = json.load(open(path, encoding="utf-8"))
            video = os.path.join(OUT, f"{name}.mp4")
            secs = build(script, video)
            print(f"[완성] {name}: {secs/60:.1f}분")
            desc, product, want = ms.build_texts(script)
            # 챕터 목차(타임스탬프 없이 장 제목만)
            toc = "\n".join(f"· {c['title']}" for c in script["chapters"])
            desc = desc.replace(script.get("description", ""), script.get("description", "") + "\n\n📖 목차\n" + toc, 1)
            yt = ms.yt_upload(video, script["title"], desc, script.get("tags", []), script.get("privacy"), shorts=False)
            thumb = os.path.join(OUT, f"{name}.jpg")
            thumbnail(script, thumb)
            msg = f"🎞 오늘의 롱폼 ({secs/60:.1f}분) · AI사진 {sum(1 for x in ms.IMG_LOG if x == 'AI')}장\n\n📌 {script['title']}\n"
            markup = None
            if yt:
                vid, privacy = yt
                ok = set_thumbnail(vid, thumb)
                msg += f"\n✅ 유튜브 {'공개' if privacy == 'public' else privacy}로 올라갔어요" + ("" if ok else "\n(썸네일 자동 설정 실패 — 스튜디오에서 첨부 이미지로 바꿔 주세요)")
                if product:
                    msg += f"\n🛒 {product[1]}"
                markup = json.dumps({"inline_keyboard": [[{"text": "▶ 영상 보기", "url": f"https://youtu.be/{vid}"}],
                                                         [{"text": "✏️ 스튜디오에서 수정", "url": f"https://studio.youtube.com/video/{vid}/edit"}]]})
            else:
                msg += "\n⚠️ 유튜브 업로드 실패 — Actions 보관함에서 영상을 받아 직접 올려 주세요"
            data = {"chat_id": ms.chat_id(), "caption": msg[:1000]}
            if markup:
                data["reply_markup"] = markup
            with open(thumb, "rb") as fh:
                ms.tg("sendPhoto", data=data, files={"photo": ("thumb.jpg", fh, "image/jpeg")})
            shutil.move(path, os.path.join(DONE, os.path.basename(path)))
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[실패] {name}: {e}")
            try:
                ms.tg("sendMessage", data={"chat_id": ms.chat_id(), "text": f"[롱폼] 제작 실패: {name}\n{str(e)[:500]}"})
            except Exception:  # noqa: BLE001
                pass
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
