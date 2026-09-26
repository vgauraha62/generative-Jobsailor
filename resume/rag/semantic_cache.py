import hashlib
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

from resume.rag.embeddings import embed_one, pack_vec, unpack_vec, cosine


def _normalize(q: str) -> str:
    q = q.lower().strip()
    q = re.sub(r"[^\w\s]", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q


def _hash_norm(norm: str) -> str:
    return hashlib.sha256(norm.encode()).hexdigest()


class SemanticCache:
    def __init__(self, user_id: int, path: Path | None = None, threshold: float = 0.82, ttl_seconds: int = 3600):
        self.user_id = user_id
        self.threshold = threshold
        self.ttl_seconds = ttl_seconds
        from resume.rag.vector_store import _rag_db_path
        self.path = path or _rag_db_path(user_id)

    def _conn(self):
        c = sqlite3.connect(str(self.path))
        c.row_factory = sqlite3.Row
        return c

    def _ensure(self):
        with self._conn() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS qa_cache(
                    q_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, q_text TEXT NOT NULL,
                    q_norm TEXT NOT NULL, embedding BLOB, answer TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now')),
                    expires_at INTEGER DEFAULT 0)""")
            try:
                con.execute("ALTER TABLE qa_cache ADD COLUMN expires_at INTEGER DEFAULT 0")
            except Exception:
                pass

    def _is_expired(self, row) -> bool:
        try:
            exp = row["expires_at"] if "expires_at" in row.keys() else 0
        except Exception:
            exp = 0
        if exp and exp != 0 and time.time() > exp:
            return True
        return False

    def get(self, question: str) -> Optional[dict]:
        self._ensure()
        norm = _normalize(question)
        h = _hash_norm(norm)
        with self._conn() as con:
            r = con.execute("SELECT * FROM qa_cache WHERE q_hash=? AND user_id=?", (h, self.user_id)).fetchone()
            if r:
                if self._is_expired(r):
                    con.execute("DELETE FROM qa_cache WHERE q_hash=? AND user_id=?", (h, self.user_id))
                    con.commit()
                else:
                    return {"answer": r["answer"], "tier": "L1", "q_hash": h, "matched_q": r["q_text"]}
            try:
                qvec = embed_one(norm, uid=self.user_id)
            except Exception:
                return None
            rows = con.execute("SELECT * FROM qa_cache WHERE user_id=?", (self.user_id,)).fetchall()
            best = None
            best_s = -1
            for row in rows:
                if self._is_expired(row):
                    continue
                blob = row["embedding"]
                if not blob:
                    continue
                try:
                    vec = unpack_vec(blob)
                except Exception:
                    continue
                s = cosine(qvec, vec)
                if s > best_s:
                    best_s = s
                    best = row
            if best is not None and best_s >= self.threshold:
                return {"answer": best["answer"], "tier": "L2", "q_hash": best["q_hash"], "matched_q": best["q_text"], "score": best_s}
        return None

    def put(self, question: str, answer: str, ttl: Optional[int] = None):
        self._ensure()
        norm = _normalize(question)
        h = _hash_norm(norm)
        try:
            vec = embed_one(norm, uid=self.user_id)
            blob = pack_vec(vec)
        except Exception:
            blob = None
        exp = 0
        if ttl is not None and ttl > 0:
            exp = int(time.time()) + int(ttl)
        elif answer == "NEEDS_REVIEW":
            exp = int(time.time()) + int(self.ttl_seconds)
        with self._conn() as con:
            con.execute("""
                INSERT OR REPLACE INTO qa_cache(q_hash,user_id,q_text,q_norm,embedding,answer,expires_at)
                VALUES(?,?,?,?,?,?,?)""", (h, self.user_id, question, norm, blob, answer, exp))

    def clear(self):
        with self._conn() as con:
            con.execute("DELETE FROM qa_cache WHERE user_id=?", (self.user_id,))

    def count(self) -> int:
        with self._conn() as con:
            try:
                r = con.execute("SELECT COUNT(*) as c FROM qa_cache WHERE user_id=?", (self.user_id,)).fetchone()
                return r["c"] if r else 0
            except Exception:
                return 0
