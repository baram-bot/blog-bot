# -*- coding: utf-8 -*-
"""고품질 AI 음성(타입캐스트) — 시니어 사연 채널(쇼츠·롱폼) 전용.

깃허브 비밀값 TYPECAST_API_KEY 가 있으면 타입캐스트로 읽고, 없으면 기존 무료 음성(edge-tts)을 쓴다.
영상 한 편 안에서 목소리가 섞이지 않도록, 도중에 타입캐스트가 실패하면(크레딧 소진 등)
ProFailed 를 던지고 → 만드는 쪽에서 그 영상을 처음부터 무료 음성으로 다시 만든다.

인물별 목소리는 타입캐스트 목소리 목록에서 성별·나이로 자동으로 고른다.
직접 고르고 싶으면 data/typecast_voices.json 에 {"grandma": "tc_...", "narrator_male": "tc_..."} 처럼 적는다.
"""
import json
import os
import threading

import requests

API = "https://api.typecast.ai"
MODEL = os.environ.get("TYPECAST_MODEL", "ssfm-v31")
KEY = os.environ.get("TYPECAST_API_KEY", "").strip()
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

_state = "off" if not KEY else "on"   # on → 타입캐스트, failed → 이번 영상 다시 만들기 필요, off → 무료 음성
_lock = threading.Lock()
_voices = {}
_pools = {}
_used = 0


class ProFailed(RuntimeError):
    pass


def active():
    if _state == "failed":
        raise ProFailed("타입캐스트 실패 — 이 영상은 무료 음성으로 다시 만든다")
    return _state == "on"


def fallback():
    """build 쪽에서 ProFailed 를 잡은 뒤 부른다: 이번 실행의 나머지는 무료 음성."""
    global _state
    _state = "off"
    print("[음성] 타입캐스트를 끄고 무료 음성으로 진행")


def _fail(msg):
    global _state
    with _lock:
        if _state == "on":
            _state = "failed"
    print(f"[음성] 타입캐스트 실패: {msg}")
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


def synth(text, role, path, tempo=1.0, prev_text=None, next_text=None):
    """타입캐스트로 mp3 를 만든다. 실패하면 ProFailed."""
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
    _fail(last)


def used():
    return _used
