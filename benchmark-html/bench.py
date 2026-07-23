#!/usr/bin/env python3
import json
import time
import sys
import requests

PROMPT = sys.argv[1] if len(sys.argv) > 1 else "hello"
URL = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8090/v1/chat/completions"
MODEL = "qwen3-4b-q6-voice"

payload = {
    "model": MODEL,          # llama-server usually ignores this, but OpenAI clients send it
    "stream": True,
    "messages": [
        #{"role": "user", "content": "Say 'hello' and then continue with one short sentence."}
        {"role": "user", "content": PROMPT}
    ],
    # keep it simple/fast:
    "temperature": 0.7,
    #"max_tokens": 64,
}

t0 = time.perf_counter()

# stream=True is critical: we want incremental chunks
with requests.post(URL, json=payload, stream=True) as r:
    r.raise_for_status()

    first_byte_t = None
    first_content_t = None
    after_think_t = None

    buf_text = ""

    # iter_content gives you first-byte timing more directly than iter_lines
    for chunk in r.iter_content(chunk_size=1):
        if not chunk:
            continue
        if first_byte_t is None:
            first_byte_t = time.perf_counter()

        # accumulate and also parse as SSE lines (OpenAI-style: "data: {...}\n\n")
        buf_text += chunk.decode("utf-8", errors="ignore")

        while "\n" in buf_text:
            line, buf_text = buf_text.split("\n", 1)
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break

            try:
                evt = json.loads(data)
            except json.JSONDecodeError:
                continue

            # OpenAI chat.completions delta path:
            delta = (evt.get("choices") or [{}])[0].get("delta") or {}
            content = delta.get("content")
            if content:
                now = time.perf_counter()
                if first_content_t is None:
                    first_content_t = now

                # optional reasoning split if the model literally streams these tags
                if after_think_t is None and "</think>" in content:
                    after_think_t = now

        if first_content_t is not None:
            # once we got first content, we can stop if you only care about TTFT
            break

t1 = time.perf_counter()

def fmt(x):
    return None if x is None else round(x, 6)

print(json.dumps({
    "ttft_first_byte_s": fmt(first_byte_t - t0) if first_byte_t else None,
    "ttft_first_content_s": fmt(first_content_t - t0) if first_content_t else None,
    "ttft_after_think_s": fmt(after_think_t - t0) if after_think_t else None,
    "total_until_stop_s": round(t1 - t0, 6),
}, indent=2))
