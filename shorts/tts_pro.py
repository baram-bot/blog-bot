# -*- coding: utf-8 -*-
"""고품질 AI 음성 — 시니어 사연 채널(쇼츠·롱폼) 전용. 섞어 쓰기:
- 해설(narrator)  → 구글 Chirp 3 HD (깃허브 비밀값 GOOGLE_TTS_API_KEY, 월 100만 자 무료)
- 인물 대사        → 타입캐스트 (비밀값 TYPECAST_API_KEY) — 할머니·할아버지·아이 목소리
한쪽 키만 있으면 그 서비스가 해설·대사를 다 맡는다(구글은 인물마다 다른 성인 목소리). 둘 다 없으면 무료 음성(edge-tts).
영상 한 편 안에서 목소리가 섞이지 않도록, 도중에 타입캐스트가 실패하면(크레딧 소진 등)
ProFailed 를 던지고 → 만드는 쪽에서 그 영상을 처음부터 무료 음성으로 다시 만든다.

인물별 목소리는 타입캐스트 목소리 목록에서 성별·나이로 자동으로 고른다.
직접 고르고 싶으면 data/typecast_voices.json 에 {"grandma": "tc_...", "narrator_male": "tc_..."} 처럼 적는다.
"""
import base64
import json
import os
import threading

import requests

API = "https://api.typecast.ai"
MODEL = os.environ.get("TYPECAST_MODEL", "ssfm-v31")
KEY = os.environ.get("TYPECAST_API_KEY", "").strip()
GKEY = os.environ.get("GOOGLE_TTS_API_KEY", "").strip()
GAPI = "https://texttospeech.googleapis.com/v1/text:synthesize"
# 구글 Chirp 3 HD 목소리(사람처럼 자연스러운 성인 목소리). 타입캐스트가 없을 때 인물별로도 나눠 쓴다.
GVOICE = {
    "narrator_male": "Charon", "narrator_female": "Sulafat",
    "grandpa": "Algenib", "grandma": "Gacrux", "father": "Iapetus", "mother": "Vindemiatrix",
    "man": "Orus", "woman": "Kore", "son": "Puck", "daughter": "Leda", "son_in_law": "Fenrir",
    "daughter_in_law": "Zephyr", "young_man": "Enceladus", "young_woman": "Aoede",
    "child": "Laomedeia", "grandchild": "Achird",
}
UA = "typecast-direct/1 python-requests typecast-integration/1 (source=api-docs; generated_by=claude-code)"
OVERRIDE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "typecast_voices.json")

# 인물 → (성별, 나이대)
ROLE = {
    "narrator_male": ("male", "middle_age"), "narrator_female": ("female", "middle_age"),
    "grandma": ("female", "elder"), "grandpa": ("male", "elder"),
    "mother": ("female", "middle_age"), "father": ("male", "middle_age"),
    "woman": ("female", "middle_age"), "man": ("male", "middle_age"),
    "young_woman": ("female", "young_adult"), "young_man": ("male", "young_adult"),
    "daughter": ("female", "young_adult"), "son": ("male", "young_adult"),
    "daughter_in_law": ("female", "young_adult"), "son_in_law": ("male", "young_adult"),
    "child": ("female", "child"), "grandchild": ("male", "child"),
}
FEMALE_EDGE = ("SunHi", "JiMin", "SeoHyeon", "SoonBok", "YuJin")

_on = {"typecast": bool(KEY), "google": bool(GKEY)}   # 켜진 서비스
_failed = None   # 도중에 실패한 서비스 → 이번 영상을 처음부터 다시 만들기
_lock = threading.Lock()
_voices = {}
_pools = {}
_used = 0
_used_g = 0


class ProFailed(RuntimeError):
    pass


def active():
    if _failed:
        raise ProFailed(f"{_failed} 실패 — 이 영상은 처음부터 다시 만든다")
    return _on["typecast"] or _on["google"]


def fallback():
    """build 쪽에서 ProFailed 를 잡은 뒤 부른다: 실패한 서비스를 끄고(이번 실행 동안) 다시 만든다."""
    global _failed
    if _failed:
        _on[_failed] = False
        print(f"[음성] {_failed} 끄고 다시 만듦 (남은 서비스: {[k for k, v in _on.items() if v] or '무료 음성'})")
    else:  # 원인 모를 때는 전부 끈다
        _on.update(typecast=False, google=False)
    _failed = None


def _fail(msg, who="typecast"):
    global _failed
    with _lock:
        if _on.get(who) and not _failed:
            _failed = who
    print(f"[음성] {who} 실패: {msg}")
    raise ProFailed(msg)


def _h():
    return {"X-API-KEY": KEY, "User-Agent": UA}


def _items(data):
    if isinstance(data, list):
        return data
    for k in ("voices", "result", "items", "data"):
        if isinstance(data.get(k), list):
            return data[k]
    return []


def _pool(gender, age):
    key = (gender, age)
    if key not in _pools:
        r = requests.get(f"{API}/v3/voices", headers=_h(), timeout=30,
                         params={"model": MODEL, "gender": gender, "age": age})
        if r.status_code != 200:
            _fail(f"목소리 목록 {r.status_code} {r.text[:200]}")
        ids = []
        for v in _items(r.json()):
            vid = v.get("voice_id") or v.get("id")
            if vid and vid.startswith("tc_"):
                ids.append(vid)
        _pools[key] = ids
    return _pools[key]


def voice_for(role):
    """인물마다 서로 다른 목소리를 고른다(같은 성별·나이대면 목록의 다음 목소리)."""
    with _lock:
        if role in _voices:
            return _voices[role]
        try:
            with open(OVERRIDE, encoding="utf-8") as fh:
                fixed = json.load(fh)
        except Exception:  # noqa: BLE001
            fixed = {}
        if fixed.get(role):
            _voices[role] = fixed[role]
            return fixed[role]
        gender, age = ROLE.get(role, ROLE["narrator_male"])
        pool = _pool(gender, age) or _pool(gender, "middle_age")
        if not pool:
            _fail(f"{role} 에 맞는 목소리 없음")
        taken = set(_voices.values())
        vid = next((v for v in pool if v not in taken), pool[0])
        _voices[role] = vid
        print(f"[음성] {role} → {vid}")
        return vid


def narrator_role(edge_voice):
    return "narrator_female" if any(n in (edge_voice or "") for n in FEMALE_EDGE) else "narrator_male"


def is_narrator(role):
    return role.startswith("narrator")


def synth(text, role, path, tempo=1.0, prev_text=None, next_text=None):
    """해설은 구글, 인물 대사는 타입캐스트(없으면 서로 대신). 실패하면 ProFailed."""
    if is_narrator(role):
        use = "google" if _on["google"] else "typecast"
    else:
        use = "typecast" if _on["typecast"] else "google"
    if use == "google":
        return _google(text, role, path, tempo)
    return _typecast(text, role, path, tempo, prev_text, next_text)


def _google(text, role, path, tempo=1.0):
    global _used_g
    name = f"ko-KR-Chirp3-HD-{GVOICE.get(role, GVOICE['narrator_male'])}"
    body = {"input": {"text": text}, "voice": {"languageCode": "ko-KR", "name": name},
            "audioConfig": {"audioEncoding": "MP3", "speakingRate": round(max(0.5, min(2.0, tempo)), 2)}}
    last = ""
    for attempt in range(3):
        try:
            r = requests.post(GAPI, params={"key": GKEY}, json=body, timeout=60)
        except Exception as e:  # noqa: BLE001
            last = str(e)
            continue
        if r.status_code == 200:
            audio = base64.b64decode(r.json().get("audioContent", ""))
            if len(audio) > 1000:
                with open(path, "wb") as fh:
                    fh.write(audio)
                with _lock:
                    _used_g += len(text)
                return
        last = f"{r.status_code} {r.text[:200]}"
        if r.status_code in (400, 401, 403):
            if r.status_code == 400 and "speakingRate" in r.text and "speakingRate" in body["audioConfig"]:
                body["audioConfig"].pop("speakingRate")  # 속도 조절을 안 받는 목소리면 기본 속도로
                continue
            break
    _fail(last, "google")


def _typecast(text, role, path, tempo=1.0, prev_text=None, next_text=None):
    global _used
    vid = voice_for(role)
    body = {"model": MODEL, "voice_id": vid, "text": text, "language": "kor",
            "output": {"audio_format": "mp3", "audio_tempo": round(max(0.5, min(2.0, tempo)), 2)}}
    if prev_text or next_text:
        body["prompt"] = {"emotion_type": "smart", "previous_text": prev_text or "", "next_text": next_text or ""}
    last = ""
    for attempt in range(3):
        try:
            r = requests.post(f"{API}/v1/text-to-speech", headers={**_h(), "Content-Type": "application/json"},
                              json=body, timeout=90)
        except Exception as e:  # noqa: BLE001
            last = str(e)
            continue
        if r.status_code == 200 and len(r.content) > 1000:
            with open(path, "wb") as fh:
                fh.write(r.content)
            with _lock:
                _used += len(text)
            return
        last = f"{r.status_code} {r.text[:200]}"
        if r.status_code in (400, 401, 402, 403):  # 키 오류·크레딧 소진 등은 다시 해도 안 됨
            break
        if body.get("prompt") and r.status_code == 422:
            body.pop("prompt", None)
    _fail(last, "typecast")


def used():
    return {"typecast": _used, "google": _used_g}
