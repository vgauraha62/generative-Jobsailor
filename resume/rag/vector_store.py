import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from resume.rag.embeddings import pack_vec, unpack_vec, cosine, embed_texts


def _rag_db_path(user_id: int) -> Path:
    p = Path(f"data/users/{user_id}/rag.db")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class VectorStore:
    def __init__(self, user_id: int, path: Path | None = None):
        self.user_id = user_id
        self.path = path or _rag_db_path(user_id)
        self._init_db()

    def _conn(self):
        c = sqlite3.connect(str(self.path))
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self):
        with self._conn() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS chunks(
                    chunk_id TEXT PRIMARY KEY,
                    parent_id TEXT,
                    user_id INTEGER NOT NULL,
                    category TEXT,
                    title TEXT,
                    content TEXT NOT NULL,
                    company TEXT,
                    role TEXT,
                    temporal_span TEXT,
                    metrics TEXT,
                    skills TEXT,
                    is_parent INTEGER DEFAULT 0,
                    embedding BLOB
                )""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_user ON chunks(user_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_parent ON chunks(parent_id)")
            try:
                con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id, content, tokenize='unicode61')")
            except Exception:
                pass
            con.execute("""
                CREATE TABLE IF NOT EXISTS qa_cache(
                    q_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    q_text TEXT NOT NULL,
                    q_norm TEXT NOT NULL,
                    embedding BLOB,
                    answer TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now')),
                    expires_at INTEGER DEFAULT 0
                )""")
            try:
                con.execute("ALTER TABLE qa_cache ADD COLUMN expires_at INTEGER DEFAULT 0")
            except Exception:
                pass
            con.execute("CREATE INDEX IF NOT EXISTS idx_qa_user ON qa_cache(user_id)")

    def upsert_records(self, records: List[dict], embeddings: List[List[float]] | None = None):
        if not records:
            return
        if embeddings is None:
            texts = [r["content"] for r in records]
            try:
                embeddings = embed_texts(texts, uid=self.user_id)
            except Exception as e:
                print(f"[rag] embed failed {e}, storing without dense vectors (BM25 only)")
                embeddings = [None] * len(records)
        with self._conn() as con:
            for rec, vec in zip(records, embeddings):
                blob = pack_vec(vec) if vec is not None else None
                con.execute("""
                    INSERT OR REPLACE INTO chunks(chunk_id,parent_id,user_id,category,title,content,company,role,temporal_span,metrics,skills,is_parent,embedding)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (rec["chunk_id"], rec["parent_id"], rec["user_id"], rec["category"], rec.get("title",""),
                     rec["content"], rec.get("company"), rec.get("role"), rec.get("temporal_span"),
                     rec.get("metrics","[]"), rec.get("skills","[]"), rec.get("is_parent",0), blob))
                try:
                    con.execute("INSERT OR REPLACE INTO chunks_fts(chunk_id, content) VALUES(?,?)",
                                (rec["chunk_id"], rec["content"]))
                except Exception:
                    pass

    def clear(self):
        with self._conn() as con:
            con.execute("DELETE FROM chunks WHERE user_id=?", (self.user_id,))
            try:
                con.execute("DELETE FROM chunks_fts")
            except Exception:
                pass

    def count(self) -> int:
        with self._conn() as con:
            r = con.execute("SELECT COUNT(*) as c FROM chunks WHERE user_id=?", (self.user_id,)).fetchone()
            return r["c"] if r else 0

    def get_all(self) -> List[dict]:
        with self._conn() as con:
            rows = con.execute("SELECT * FROM chunks WHERE user_id=?", (self.user_id,)).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d.pop("embedding", None)
                out.append(d)
            return out

    def get_parent(self, parent_id: str) -> Optional[dict]:
        with self._conn() as con:
            r = con.execute("SELECT * FROM chunks WHERE chunk_id=?", (parent_id,)).fetchone()
            if r:
                d = dict(r)
                d.pop("embedding", None)
                return d
            return None

    def dense_search(self, query_vec: List[float], top_k: int = 10, parent_only: bool = False) -> List[dict]:
        with self._conn() as con:
            q = "SELECT * FROM chunks WHERE user_id=?"
            params: list = [self.user_id]
            if parent_only:
                q += " AND is_parent=1"
            rows = con.execute(q, params).fetchall()
            scored = []
            for r in rows:
                d = dict(r)
                blob = d.pop("embedding", None)
                if not blob:
                    continue
                try:
                    vec = unpack_vec(blob)
                except Exception:
                    continue
                s = cosine(query_vec, vec)
                d["_dense_score"] = s
                d["_dense_rank"] = 0
                scored.append(d)
            scored.sort(key=lambda x: x["_dense_score"], reverse=True)
            for i, s in enumerate(scored):
                s["_dense_rank"] = i + 1
            return scored[:top_k]

    def bm25_search(self, query: str, top_k: int = 10, parent_only: bool = False) -> List[dict]:
        q = query.strip().replace('"', ' ').strip()
        if not q:
            return []
        try:
            with self._conn() as con:
                fts_q = " OR ".join(f'"{t}"' for t in q.split()[:12] if len(t) > 1)
                if not fts_q:
                    return []
                rows = con.execute(
                    "SELECT c.* FROM chunks_fts f JOIN chunks c ON c.chunk_id=f.chunk_id WHERE chunks_fts MATCH ? AND c.user_id=? LIMIT ?",
                    (fts_q, self.user_id, top_k * 3)
                ).fetchall()
                out = []
                seen = set()
                for r in rows:
                    d = dict(r)
                    d.pop("embedding", None)
                    if d["chunk_id"] in seen:
                        continue
                    seen.add(d["chunk_id"])
                    if parent_only and d.get("is_parent") != 1:
                        continue
                    d["_bm25_rank"] = len(out) + 1
                    out.append(d)
                    if len(out) >= top_k:
                        break
                return out
        except Exception:
            pass
        with self._conn() as con:
            like = f"%{q.split()[0]}%" if q.split() else "%"
            rows = con.execute(
                "SELECT * FROM chunks WHERE user_id=? AND content LIKE ? LIMIT ?",
                (self.user_id, like, top_k)
            ).fetchall()
            out = []
            for i, r in enumerate(rows):
                d = dict(r)
                d.pop("embedding", None)
                if parent_only and d.get("is_parent") != 1:
                    continue
                d["_bm25_rank"] = i + 1
                out.append(d)
            return out
