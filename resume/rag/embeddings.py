import math
import struct
from typing import List


DIM = 768


def _load_api_key(uid: int | None = None) -> str | None:
    import os
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv()
    key = os.getenv("GEMINI_API_KEY")
    if key:
        return key
    if uid is not None:
        p = Path(f"data/users/{uid}/.env.gemini")
        if p.exists():
            try:
                for line in p.read_text().splitlines():
                    if line.startswith("GEMINI_API_KEY="):
                        v = line.split("=", 1)[1].strip()
                        if v:
                            return v
            except Exception:
                pass
    return None

def _genai_embed(texts: List[str], uid: int | None = None) -> List[List[float]]:
    from google import genai
    import os
    key = _load_api_key(uid)
    if not key:
        raise RuntimeError("GEMINI_API_KEY required for rag embeddings (FAIL-closed)")
    client = genai.Client(api_key=key)
    out: List[List[float]] = []
    for t in texts:
        r = client.models.embed_content(model="text-embedding-004", contents=t)
        emb = None
        if hasattr(r, "embeddings") and r.embeddings:
            emb = r.embeddings[0].values
        elif hasattr(r, "embedding") and r.embedding:
            emb = r.embedding.values if hasattr(r.embedding, "values") else r.embedding
        else:
            emb = list(r) if isinstance(r, list) else None
        if emb is None:
            raise RuntimeError(f"embedding failed for text len={len(t)}")
        vals = list(emb)[:DIM]
        if len(vals) < DIM:
            vals += [0.0] * (DIM - len(vals))
        n = math.sqrt(sum(x * x for x in vals)) or 1.0
        vals = [x / n for x in vals]
        out.append(vals)
    return out


def embed_texts(texts: List[str], dim: int = DIM, uid: int | None = None) -> List[List[float]]:
    if not texts:
        return []
    return _genai_embed(texts, uid=uid)


def embed_one(text: str, dim: int = DIM, uid: int | None = None) -> List[float]:
    return embed_texts([text], dim, uid=uid)[0]


def pack_vec(vec: List[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_vec(b: bytes) -> List[float]:
    n = len(b) // 4
    return list(struct.unpack(f"{n}f", b))


def cosine(a: List[float], b: List[float]) -> float:
    s = sum(x * y for x, y in zip(a, b))
    return max(-1.0, min(1.0, s))
