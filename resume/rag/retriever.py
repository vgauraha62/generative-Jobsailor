from typing import List, Dict, Any
from resume.rag.vector_store import VectorStore
from resume.rag.embeddings import embed_one


def rrf_fuse(dense: List[dict], sparse: List[dict], k: int = 60, top_k: int = 5) -> List[dict]:
    scores: Dict[str, float] = {}
    by_id: Dict[str, dict] = {}
    for rank, d in enumerate(dense, 1):
        cid = d["chunk_id"]
        scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank)
        by_id[cid] = d
    for rank, d in enumerate(sparse, 1):
        cid = d["chunk_id"]
        scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank)
        if cid not in by_id:
            by_id[cid] = d
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    out = []
    for cid, sc in ranked[:top_k]:
        d = dict(by_id[cid])
        d["_rrf_score"] = sc
        out.append(d)
    return out


class Retriever:
    def __init__(self, vector_store: VectorStore):
        self.vs = vector_store

    def retrieve(self, query: str, top_k: int = 5, dense_k: int = 10, sparse_k: int = 10, parent_only: bool = False, rrf_k: int = 60) -> List[dict]:
        q = query.strip()
        if not q:
            return []
        sparse = self.vs.bm25_search(q, top_k=sparse_k, parent_only=parent_only)
        try:
            qvec = embed_one(q, uid=self.vs.user_id)
            dense = self.vs.dense_search(qvec, top_k=dense_k, parent_only=parent_only)
            fused = rrf_fuse(dense, sparse, k=rrf_k, top_k=top_k)
        except Exception as e:
            fused = sparse[:top_k]
            for d in fused:
                d["_rrf_score"] = 1.0 / (60 + d.get("_bm25_rank", 1))
        enriched = []
        for d in fused:
            if d.get("is_parent") == 0 and d.get("parent_id"):
                parent = self.vs.get_parent(d["parent_id"])
                if parent:
                    d["_parent"] = parent
            enriched.append(d)
        return enriched
