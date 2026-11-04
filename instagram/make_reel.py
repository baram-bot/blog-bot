# -*- coding: utf-8 -*-
"""카드뉴스 이미지들 → 세로 릴스 영상(1080x1920): 천천히 다가가는 움직임 + 장 넘김 + AI 음성 읽기."""
import asyncio
import json
import os
import subprocess
import sys

from PIL import Image

W, H = 1080, 1920
VOICE = "ko-KR-SunHiNeural"


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def dur(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], text=True)
    return float(out.strip() or 0)


async def _tts(text, path):
    import edge_tts
    await edge_tts.Communicate(text, VOICE, rate="+5%").save(path)


def tts(text, path):
    asyncio.run(_tts(text, path))


def scripts(spec):
    """카드마다 읽을 문장."""
    import make_cards as mc
    c = spec["cover"]
    out = [mc.noemo(f"{c.get('kicker', '')}. {c['title']}. {c.get('sub', '')}")]
    for s in spec["slides"]:
        out.append(mc.noemo(s["head"] + ". " + " ".join(s.get("lines", []))))
    out.append(mc.noemo(spec.get("cta", "") + ". 저장해 두고, 자세한 내용은 프로필 링크에서 확인하세요."))
    return out


def build(spec, card_paths, workdir, out_path):
    os.makedirs(workdir, exist_ok=True)
    texts = scripts(spec)
    clips = []
    for i, (card, text) in enumerate(zip(card_paths, texts)):
        im = Image.open(card).convert("RGB")
        canvas = Image.new("RGB", (W, H), im.getpixel((5, 600)))
        canvas.paste(im, (0, (H - im.height) // 2))
        frame = os.path.join(workdir, f"f{i}.png")
        canvas.save(frame)
        audio = os.path.join(workdir, f"a{i}.mp3")
        tts(text, audio)
        d = max(2.5, dur(audio) + 0.5)
        n = int(d * 30)
        clip = os.path.join(workdir, f"c{i}.mp4")
        run(["ffmpeg", "-y", "-loop", "1", "-i", frame, "-i", audio,
             "-vf", f"scale=2160:-1,zoompan=z='min(zoom+0.0006,1.06)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps=30,format=yuv420p",
             "-af", "apad", "-t", f"{d:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-c:a", "aac", "-b:a", "128k", "-ar", "44100", clip])
        clips.append(clip)
    lst = os.path.join(workdir, "list.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{c}'\n" for c in clips)
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out_path])
    return dur(out_path)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import make_cards
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    cards = make_cards.build(spec, sys.argv[2])
    print(build(spec, cards, sys.argv[2] + "/reel", sys.argv[2] + "/reel.mp4"))
