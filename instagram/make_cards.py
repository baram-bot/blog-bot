# -*- coding: utf-8 -*-
"""인스타 카드뉴스(캐러셀) 만들기: 대본 JSON → 1080x1350 PNG 여러 장.
대본 형식: {"corner": "💼 자영업자의 경제노트", "cover": {"kicker": "...", "title": "...", "sub": "..."},
          "slides": [{"head": "...", "lines": ["...", "..."]}], "cta": "...", "bg": "path(선택)"}
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1350
FONTS = {"black": "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
         "bold": "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
         "reg": "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"}
THEMES = {  # 코너별 색(배경, 강조, 글씨)
    "👶": ((255, 246, 232), (255, 140, 66), (40, 32, 28)),
    "💼": ((233, 241, 255), (34, 99, 230), (18, 28, 48)),
    "👴": ((245, 239, 228), (166, 98, 52), (44, 34, 26)),
    "📻": ((245, 239, 228), (166, 98, 52), (44, 34, 26)),
    "🏠": ((236, 248, 240), (34, 150, 96), (22, 40, 30)),
    "🤖": ((236, 236, 250), (96, 72, 220), (24, 22, 48)),
    "🔥": ((22, 22, 30), (255, 70, 70), (250, 250, 252)),   # 오늘의 핫이슈: 어두운 바탕 + 빨강
    "🎬": ((22, 20, 32), (255, 190, 30), (250, 250, 252)),  # 연예 소식: 어두운 바탕 + 노랑
}


def font(kind, size):
    path = FONTS[kind]
    for idx in range(10):
        try:
            f = ImageFont.truetype(path, size, index=idx)
            if "KR" in " ".join(f.getname()):
                return f
        except Exception:  # noqa: BLE001
            break
    return ImageFont.truetype(path, size)


def wrap(d, text, f, maxw):
    out, line = [], ""
    for word in text.split(" "):
        test = (line + " " + word).strip()
        if d.textlength(test, font=f) <= maxw:
            line = test
            continue
        if line:
            out.append(line)
        line = word
        while d.textlength(line, font=f) > maxw:  # 아주 긴 단어는 글자 단위로
            for i in range(len(line), 0, -1):
                if d.textlength(line[:i], font=f) <= maxw:
                    out.append(line[:i])
                    line = line[i:]
                    break
    if line:
        out.append(line)
    return out


import re as _re
_EMO = _re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]")


def noemo(t):
    return _EMO.sub("", t or "").strip()


def theme(corner):
    for k, v in THEMES.items():
        if corner.startswith(k):
            return v
    return THEMES["💼"]


def base(bgc, acc, page, total, corner, handle):
    img = Image.new("RGB", (W, H), bgc)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 14], fill=acc)
    f = font("bold", 34)
    label = noemo(corner)
    white_bg = bgc == (255, 255, 255) or acc == (255, 255, 255)
    pill, txt = (acc, (255, 255, 255)) if not white_bg else ((255, 255, 255), bgc)
    d.rounded_rectangle([60, 60, 60 + d.textlength(label, font=f) + 56, 128], radius=34, fill=pill)
    d.text((88, 70), label, font=f, fill=txt)
    fs = font("reg", 30)
    d.text((60, H - 84), handle, font=fs, fill=tuple(int(c * 0.55) for c in acc))
    pg = f"{page}/{total}"
    d.text((W - 60 - d.textlength(pg, font=fs), H - 84), pg, font=fs, fill=tuple(int(c * 0.55) for c in acc))
    return img, d


def cover(spec, bgc, acc, fg, total, corner, handle, bgpath=None):
    img, d = base(bgc, acc, 1, total, corner, handle)
    if bgpath and os.path.exists(bgpath):  # 대표 그림 한 장(위쪽 절반)
        ph = Image.open(bgpath).convert("RGB")
        r = max(W / ph.width, 620 / ph.height)
        ph = ph.resize((int(ph.width * r), int(ph.height * r)))
        ph = ph.crop(((ph.width - W) // 2, 0, (ph.width - W) // 2 + W, 620))
        img.paste(ph, (0, 160))
        d = ImageDraw.Draw(img)
        y = 820
    else:
        y = 380
    fk = font("bold", 46)
    d.text((70, y), noemo(spec.get("kicker", "")), font=fk, fill=acc)
    y += 80
    ft = font("black", 112 if not bgpath else 84)
    for ln in wrap(d, noemo(spec["title"]), ft, W - 140):
        d.text((70, y), ln, font=ft, fill=fg)
        y += int(ft.size * 1.22)
    y += 30
    fsub = font("reg", 44)
    for ln in wrap(d, noemo(spec.get("sub", "")), fsub, W - 140):
        d.text((70, y), ln, font=fsub, fill=tuple(int(c * 0.8 + 40) for c in fg))
        y += 64
    d.text((70, H - 170), "옆으로 넘겨 보세요  →", font=font("bold", 40), fill=acc)
    return img


def slide(spec, i, bgc, acc, fg, total, corner, handle):
    img, d = base(bgc, acc, i, total, corner, handle)
    fn = font("black", 120)
    d.text((70, 190), f"{i - 1:02d}", font=fn, fill=acc)
    fh = font("black", 70)
    y = 360
    for ln in wrap(d, noemo(spec["head"]), fh, W - 140):
        d.text((70, y), ln, font=fh, fill=fg)
        y += 92
    y += 40
    d.rectangle([70, y, 190, y + 8], fill=acc)
    y += 60
    fl = font("reg", 46)
    for item in spec.get("lines", []):
        lines = wrap(d, noemo(item), fl, W - 190)
        d.ellipse([74, y + 22, 94, y + 42], fill=acc)
        for ln in lines:
            d.text((120, y), ln, font=fl, fill=fg)
            y += 66
        y += 26
    return img


def cta(text, n, bgc, acc, fg, total, corner, handle, points=None):
    img, d = base(acc, (255, 255, 255), n, total, corner, handle)  # 마지막 장: 강조색 바탕
    d = ImageDraw.Draw(img)
    ft = font("black", 80)
    y = 420
    for ln in wrap(d, noemo(text), ft, W - 140):
        d.text((70, y), ln, font=ft, fill=(255, 255, 255))
        y += 104
    y += 60
    for t in (points or ("저장해 두고 필요할 때 꺼내 보세요", "자세한 내용은 프로필 링크 블로그에", "궁금한 건 댓글로 물어봐 주세요"))[:3]:
        d.ellipse([74, y + 20, 96, y + 42], fill=(255, 255, 255))
        d.text((120, y), t, font=font("bold", 44), fill=(255, 255, 255))
        y += 84
    # 맨 아래 팔로우 부탁 상자(흰 바탕 + 강조색 글씨)
    by = H - 330
    d.rounded_rectangle([60, by, W - 60, by + 200], radius=36, fill=(255, 255, 255))
    f1, f2 = font("black", 50), font("bold", 40)
    t1 = "더 좋은 정보, 계속 받아보시려면"
    t2 = f"팔로우 부탁드려요  {handle}"
    d.text(((W - d.textlength(t1, font=f1)) / 2, by + 34), t1, font=f1, fill=acc)
    d.text(((W - d.textlength(t2, font=f2)) / 2, by + 116), t2, font=f2, fill=(40, 40, 40))
    return img


def build(spec, outdir, handle="@gureum_happy_story"):
    os.makedirs(outdir, exist_ok=True)
    corner = spec.get("corner", "💼 자영업자의 경제노트")
    bgc, acc, fg = theme(corner)
    total = len(spec["slides"]) + 2
    pages = [cover(spec["cover"], bgc, acc, fg, total, corner, handle, spec.get("bg"))]
    pages += [slide(s, i + 2, bgc, acc, fg, total, corner, handle) for i, s in enumerate(spec["slides"])]
    pages.append(cta(spec.get("cta", "오늘 정보, 도움 되셨나요?"), total, bgc, acc, fg, total, corner, handle,
                     [noemo(x) for x in spec.get("cta_lines", [])] or None))
    paths = []
    for i, p in enumerate(pages, 1):
        path = os.path.join(outdir, f"card{i}.png")
        p.save(path)
        paths.append(path)
    return paths


if __name__ == "__main__":
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    print("\n".join(build(spec, sys.argv[2])))
