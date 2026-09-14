#!/usr/bin/env python3
"""KV-cache size for the compose model, read from the GGUF header.

    ./kv-bench/kv-size.py [model.gguf ...]

Only `full_attention` layers carry a KV cache: Qwen3.8-Flash-Next runs 3 of
every 4 blocks as Gated DeltaNet, whose recurrent state is unaffected by
-ctk/-ctv. QSA sparse attention (`attention.indexer.top_k`) further caps how
many cached entries a decode step actually reads -- which is why shrinking the
cache does not buy throughput on this architecture.
"""

import struct
import sys

DEFAULT = ("/home/bdawg/.cache/huggingface/hub/models--unsloth--Qwen3.8-Flash-Next-GGUF/"
           "snapshots/8bdc666649440e9bdc97e16f3f75782c98478ff5/UD-IQ4_XS/"
           "Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00003.gguf")

TYPES = {0: "u8", 1: "i8", 2: "u16", 3: "i16", 4: "u32", 5: "i32", 6: "f32",
         7: "bool", 8: "string", 9: "array", 10: "u64", 11: "i64", 12: "f64"}
FMT = {"u8": "<B", "i8": "<b", "u16": "<H", "i16": "<h", "u32": "<I", "i32": "<i",
       "f32": "<f", "bool": "<B", "u64": "<Q", "i64": "<q", "f64": "<d"}

# llama.cpp cache types: bits per value including the per-block scale
QUANT = {"f16": 16.0, "q8_0": 8.5, "q4_0": 4.5}


def read_header(path):
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError(f"{path}: not GGUF")
        version = struct.unpack("<I", f.read(4))[0]
        n_tensors, n_kv = struct.unpack("<QQ", f.read(16))

        def rstring():
            n = struct.unpack("<Q", f.read(8))[0]
            return f.read(n).decode("utf-8", "replace")

        meta = {}
        for _ in range(n_kv):
            key = rstring()
            t = TYPES[struct.unpack("<I", f.read(4))[0]]
            if t == "string":
                meta[key] = rstring()
            elif t == "bool":
                meta[key] = struct.unpack("<B", f.read(1))[0] != 0
            elif t == "array":
                el = TYPES[struct.unpack("<I", f.read(4))[0]]
                n = struct.unpack("<Q", f.read(8))[0]
                meta[key] = [rstring() if el == "string"
                             else struct.unpack(FMT[el], f.read(struct.calcsize(FMT[el])))[0]
                             for _ in range(n)]
            else:
                meta[key] = struct.unpack(FMT[t], f.read(struct.calcsize(FMT[t])))[0]
    return meta, n_tensors, version


def main(paths):
    for path in paths or [DEFAULT]:
        meta, _, _ = read_header(path)
        arch = meta.get("general.architecture", "?")
        g = lambda key, d=None: meta.get(f"{arch}.{key}", d)
        blocks = g("block_count", 0)
        interval = g("full_attention_interval", 1) or 1
        n_full = blocks // interval
        kv_heads = g("attention.head_count_kv", 0)
        dims = g("attention.key_length", 0) + g("attention.value_length", 0)
        per_tok = n_full * kv_heads * dims
        top_k = g("attention.indexer.top_k", 0)

        print(f"{path}\n  arch={arch} name={meta.get('general.name', '?')} blocks={blocks} "
              f"full_attention={n_full} (every {interval}th layer) kv_heads={kv_heads} "
              f"head_dim={g('attention.key_length')} qsa_top_k={top_k or 'off'}")
        print(f"  {per_tok} KV elements/token -> " + ", ".join(
            f"{name}={per_tok * bits / 8 / 1024:.2f} KiB/token" for name, bits in QUANT.items()))
        for ctx in (8192, 32768, 131072, 262144):
            gib = {name: per_tok * bits / 8 * ctx / 2**30 for name, bits in QUANT.items()}
            parts = [f"f16={gib['f16']:.2f} GiB"]
            parts += [f"{name}={gib[name]:.2f} GiB ({gib[name] / gib['f16']:.0%})"
                      for name in ("q8_0", "q4_0")]
            print(f"  ctx {ctx:>6}: " + "  ".join(parts))
        if top_k:
            step = n_full * top_k * kv_heads * dims / 8  # bytes read per generated token
            print(f"  decode reads <= {top_k} entries/layer: {step / 2**20:.1f} MiB/token "
                  f"f16 = {step * 20 / 2**30:.2f} GiB/s at 20 tok/s")


if __name__ == "__main__":
    main(sys.argv[1:] or [DEFAULT])
