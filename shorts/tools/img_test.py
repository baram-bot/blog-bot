import base64, json, os, time, urllib.parse, requests
P = "elderly Korean grandmother smiling warmly at her grown son at a wooden table, warm evening light, photorealistic, cinematic, vertical"
out = []
def log(m):
    print(m); out.append(m)
# A pollinations anonymous
for url in [f"https://image.pollinations.ai/prompt/{urllib.parse.quote(P)}?width=768&height=1344&nologo=true&model=flux&referrer=baramshorts",
            f"https://image.pollinations.ai/prompt/{urllib.parse.quote(P)}?width=768&height=1344&nologo=true&model=turbo"]:
    try:
        r = requests.get(url, timeout=90)
        log(f"pollinations {r.status_code} {r.headers.get('content-type')} {len(r.content)}")
        if r.ok and r.headers.get('content-type','').startswith('image'):
            open('shorts/_polli.jpg','wb').write(r.content)
    except Exception as e: log(f"pollinations err {e}")
    time.sleep(16)
key = os.environ.get("GEMINI_API_KEY","")
log(f"gemini key: {'yes' if key else 'no'}")
if key:
    for model in ["gemini-2.5-flash-image","gemini-2.0-flash-preview-image-generation","gemini-2.0-flash-exp-image-generation"]:
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
                json={"contents":[{"parts":[{"text":"Generate an image: "+P}]}],
                      "generationConfig":{"responseModalities":["TEXT","IMAGE"]}}, timeout=120)
            ok = False
            if r.ok:
                for c in r.json().get("candidates",[]):
                    for p in c.get("content",{}).get("parts",[]):
                        if "inlineData" in p:
                            open(f"shorts/_g_{model}.png","wb").write(base64.b64decode(p["inlineData"]["data"])); ok=True
            log(f"{model} {r.status_code} image={ok} {'' if r.ok else r.text[:200]}")
        except Exception as e: log(f"{model} err {e}")
    for model in ["imagen-4.0-fast-generate-001","imagen-3.0-generate-002"]:
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predict?key={key}",
                json={"instances":[{"prompt":P}],"parameters":{"sampleCount":1,"aspectRatio":"9:16"}}, timeout=120)
            log(f"{model} {r.status_code} {r.text[:150] if not r.ok else 'OK'}")
        except Exception as e: log(f"{model} err {e}")
log("cf/hf tokens: " + ",".join(k for k in ["CF_API_TOKEN","HF_TOKEN","PEXELS_API_KEY","PIXABAY_API_KEY"] if os.environ.get(k)))
open("data/img_test.txt","w").write("\n".join(out))
