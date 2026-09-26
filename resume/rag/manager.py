import re
import json
import hashlib
import time
from pathlib import Path
from typing import Dict, Any, Optional, List

from web.per_user import get_user_shard, get_user_profile_path, get_user_visited_path, get_user_reports_dir
from resume.rag.chunker import chunk_resume, chunks_to_records
from resume.rag.vector_store import VectorStore
from resume.rag.retriever import Retriever
from resume.rag.semantic_cache import SemanticCache
from resume.rag.verifier import verify_answer, guard
from resume.rag.router import classify_query, RouteTarget

try:
    from cachetools import LRUCache
except ImportError:
    class LRUCache(dict):
        def __init__(self, maxsize=100): super().__init__(); self.maxsize=maxsize

_MANAGERS: LRUCache = LRUCache(maxsize=100)


def get_manager(user_id: int) -> "RAGManager":
    uid = int(user_id)
    if uid in _MANAGERS:
        return _MANAGERS[uid]
    m = RAGManager(uid)
    _MANAGERS[uid] = m
    return m


def invalidate_manager(user_id: int):
    uid = int(user_id)
    _MANAGERS.pop(uid, None)


class RAGManager:
    def __init__(self, user_id: int):
        self.user_id = int(user_id)
        self.shard = get_user_shard(self.user_id)
        self.vector_store = VectorStore(self.user_id)
        self.retriever = Retriever(self.vector_store)
        self.cache = SemanticCache(self.user_id)

    def ingest_resume(self, md_text: str, filename: str = "") -> Dict[str, Any]:
        parents = chunk_resume(md_text, self.user_id)
        records = chunks_to_records(parents)
        self.vector_store.clear()
        self.cache.clear()
        self.vector_store.upsert_records(records)
        return {"parents": len(parents), "chunks": len(records), "children": len(records) - len(parents)}

    def ingest_file(self, md_path: str | Path) -> Dict[str, Any]:
        p = Path(md_path)
        text = p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""
        return self.ingest_resume(text, p.name)

    def _ensure_index(self):
        if self.vector_store.count() > 0:
            return
        for cand in [self.shard / "resumes" / "base.md", Path("resumes/base.md")]:
            if cand.exists():
                try:
                    self.ingest_file(cand)
                except Exception as e:
                    print(f"[rag] auto-reindex failed: {e}")
                break

    def _direct_lookup(self, query: str, target_key: Optional[str], domain: str) -> Optional[str]:
        low = query.lower()
        try:
            pp = get_user_profile_path(self.user_id)
            if pp.exists():
                prof = json.loads(pp.read_text(encoding="utf-8"))
            else:
                from candidate_profile import load_candidate_profile
                prof = load_candidate_profile()
            facts = prof.get("resume_facts", {})
            prefs = prof.get("user_preferences", {})
            merged = {**facts, **prefs}
            alias = {"qualification": "highest_qualification", "skills": "skills", "phone": "phone", "email": "email", "expected_ctc": "expected_ctc_lpa", "current_ctc": "current_ctc_lpa", "ctc": "expected_ctc_lpa", "notice_period": "notice_period_days", "location": "current_location", "experience": "total_experience_years"}
            if target_key and target_key in alias:
                k2 = alias[target_key]
                if k2 in merged:
                    v = merged[k2]
                    s = str(v)
                    if v == "NEEDS_REVIEW":
                        return "NEEDS_REVIEW"
                    if target_key == "skills" and len(s.split()) > 20 and "pipeline" in s.lower():
                        return None
                    return s
            if target_key and target_key in merged:
                v = merged[target_key]
                s = str(v)
                if v == "NEEDS_REVIEW":
                    return "NEEDS_REVIEW"
                if target_key == "skills" and len(s.split()) > 20 and "pipeline" in s.lower():
                    return None
                return s
            for k, v in merged.items():
                if k.lower() in low and str(v).strip():
                    return str(v) if v != "NEEDS_REVIEW" else "NEEDS_REVIEW"
            if any(w in low for w in ["phone","mobile"]):
                return str(merged.get("phone","NEEDS_REVIEW"))
            if "email" in low:
                return str(merged.get("email","NEEDS_REVIEW"))
            if "ctc" in low:
                if "expected" in low:
                    return str(merged.get("expected_ctc_lpa","NEEDS_REVIEW"))
                return str(merged.get("current_ctc_lpa","NEEDS_REVIEW"))
            if "notice" in low:
                return str(merged.get("notice_period_days","NEEDS_REVIEW"))
            if "location" in low:
                return str(merged.get("current_location","NEEDS_REVIEW"))
            if "authorization" in low or "visa" in low or "citizen" in low:
                return str(merged.get("work_authorization","NEEDS_REVIEW"))
        except Exception:
            pass
        if domain == "reports":
            try:
                vp = get_user_visited_path(self.user_id)
                if vp.exists():
                    data = json.loads(vp.read_text(encoding="utf-8"))
                    if "http" in low:
                        for url, meta in data.items():
                            if url.lower() in low:
                                return json.dumps(meta)
                    return json.dumps({"total": len(data), "sample": list(data.items())[:3]})
                rep_dir = get_user_reports_dir(self.user_id)
                files = list(rep_dir.glob("visit_*.json"))
                if files:
                    latest = sorted(files)[-1]
                    return latest.read_text(encoding="utf-8")[:3000]
            except Exception:
                pass
        return None

    def _reports_structured(self, q: str) -> dict | None:
        low = q.lower()
        try:
            vp = get_user_visited_path(self.user_id)
            visited = {}
            if vp.exists():
                visited = json.loads(vp.read_text(encoding="utf-8"))
            rep_dir = get_user_reports_dir(self.user_id)
            latest_visit = None
            latest_summary = {}
            visits = sorted(rep_dir.glob("visit_*.json"))
            if visits:
                try:
                    latest_visit = json.loads(visits[-1].read_text(encoding="utf-8"))
                    latest_summary = latest_visit.get("summary", {})
                except Exception:
                    pass
            by_status = {}
            if visited:
                from collections import Counter
                c = Counter(v.get("status","unknown") for v in visited.values())
                by_status = dict(c)
            elif latest_summary.get("by_status"):
                by_status = latest_summary["by_status"]
            total = len(visited) if visited else latest_summary.get("by_status",{}).get("applied",0) + latest_summary.get("by_status",{}).get("failed",0) + latest_summary.get("by_status",{}).get("skipped",0)
            is_complex = any(w in low for w in ["analyze","compare","why irregular","gap","tailor"])
            if is_complex:
                return None
            if any(w in low for w in ["fail","failed","failure","succeed","success"]):
                ans = f"Applications: total {total}, by_status {json.dumps(by_status)}"
                if latest_summary:
                    ans += f", latest run {latest_summary.get('by_status')}"
                    if latest_visit and latest_visit.get("results"):
                        fails = [r for r in latest_visit["results"] if r.get("status")=="failed"][:3]
                        if fails:
                            ans += f", recent failures: {'; '.join(r.get('reason','')[:80] for r in fails)}"
                return {"answer": ans, "by_status": by_status, "total": total, "latest_summary": latest_summary}
            if "how many" in low or "count" in low or "applied" in low:
                return {"answer": f"Total {total}, by_status {json.dumps(by_status)}", "by_status": by_status, "total": total}
            return {"answer": f"Applications: total {total}, by_status {json.dumps(by_status)}", "by_status": by_status, "total": total}
        except Exception as e:
            return None

    def _profile_structured(self, q: str) -> dict | None:
        low = q.lower()
        keys = []
        if "expected" in low and "ctc" in low: keys.append("expected_ctc")
        elif "current" in low and "ctc" in low: keys.append("current_ctc")
        elif "ctc" in low: keys.append("expected_ctc")
        if "notice" in low: keys.append("notice_period")
        if "location" in low or "city" in low: keys.append("location")
        if "work authorization" in low or "visa" in low or "citizen" in low: keys.append("work_authorization")
        if "qualification" in low or "degree" in low: keys.append("qualification")
        if "experience" in low and "year" in low: keys.append("experience")
        if "skill" in low or "tool" in low: keys.append("skills")
        if len(keys) <= 1:
            return None
        try:
            pp = get_user_profile_path(self.user_id)
            if pp.exists():
                prof = json.loads(pp.read_text(encoding="utf-8"))
            else:
                from candidate_profile import load_candidate_profile
                prof = load_candidate_profile()
            facts = prof.get("resume_facts", {})
            prefs = prof.get("user_preferences", {})
            merged = {**facts, **prefs}
            alias = {"expected_ctc":"expected_ctc_lpa","current_ctc":"current_ctc_lpa","notice_period":"notice_period_days","location":"current_location","work_authorization":"work_authorization","qualification":"highest_qualification","experience":"total_experience_years","skills":"skills"}
            parts = []
            for k in keys:
                ak = alias.get(k, k)
                v = merged.get(ak, "NEEDS_REVIEW")
                if v != "NEEDS_REVIEW" and str(v).strip():
                    if k == "expected_ctc": parts.append(f"Expected CTC: {v} LPA")
                    elif k == "current_ctc": parts.append(f"Current CTC: {v} LPA")
                    elif k == "notice_period": parts.append(f"Notice: {v} days")
                    elif k == "location": parts.append(f"Location: {v}")
                    elif k == "qualification": parts.append(f"Qualification: {v}")
                    elif k == "experience": parts.append(f"Experience: {v} years")
                    elif k == "skills": parts.append(f"Skills: {v}")
                    else: parts.append(f"{k}: {v}")
            if not parts:
                return None
            return {"answer": ", ".join(parts), "keys": keys}
        except Exception:
            return None

    def _build_structured_context(self, retrieved_chunks: list) -> dict:
        """Organizes parsed autofill facts, preferences, and resume chunks into a clean JSON structure."""
        facts, prefs = {}, {}
        try:
            pp = get_user_profile_path(self.user_id)
            if pp.exists():
                prof = json.loads(pp.read_text(encoding="utf-8"))
                facts = prof.get("resume_facts", {})
                prefs = prof.get("user_preferences", {})
        except Exception:
            pass

        all_chunks = self.vector_store.get_all()
        parents = [c for c in all_chunks if c.get("is_parent") == 1]
        
        work_experience = []
        seen_titles = set()
        for p in parents:
            comp = p.get("company") or ""
            role = p.get("role") or ""
            dates = p.get("temporal_span") or ""
            title = p.get("title") or ""
            
            if not comp and not role:
                m_job = re.search(r'([A-Za-z0-9\/\s\-]+?),\s*([A-Za-z0-9\s\(\)\.,\-]+?)\s*[-–]\s*([A-Za-z]+\s*\d{4}.*?(?:Present|\d{4}))', title or p.get("content", "")[:200])
                if m_job:
                    role = m_job.group(1).strip()
                    comp = m_job.group(2).strip()
                    dates = m_job.group(3).strip()
            
            if (comp or role) and title not in seen_titles:
                if "resume" in (title or "").lower() and not comp:
                    continue
                seen_titles.add(title)
                bullets = [l.strip().lstrip('•*-– ') for l in p.get("content", "").splitlines() if len(l.strip()) > 20 and not l.startswith("#")][:4]
                work_experience.append({
                    "role": role or "Engineer / Specialist",
                    "company": comp or title,
                    "dates": dates,
                    "achievements": bullets
                })

        all_skills = set()
        all_metrics = []
        for c in all_chunks:
            try:
                s = json.loads(c.get("skills", "[]")) if isinstance(c.get("skills"), str) else c.get("skills", [])
                if isinstance(s, list): all_skills.update(s)
            except: pass
            try:
                m_val = json.loads(c.get("metrics", "[]")) if isinstance(c.get("metrics"), str) else c.get("metrics", [])
                if isinstance(m_val, list): all_metrics.extend(m_val)
            except: pass

        relevant_sections = []
        for c in retrieved_chunks:
            sec_text = c.get("content", "")
            if c.get("_parent") and isinstance(c["_parent"], dict):
                sec_text = sec_text + "\n" + c["_parent"].get("content", "")[:300]
            relevant_sections.append(sec_text[:400])

        return {
            "candidate_profile": facts,
            "user_preferences": prefs,
            "work_experience": work_experience,
            "skills": sorted(all_skills)[:25],
            "quantified_metrics": list(dict.fromkeys(all_metrics))[:12],
            "relevant_sections": relevant_sections[:4]
        }

    def _work_history_structured(self, q: str) -> dict | None:
        low = q.lower().strip()
        work_hints = [
            "work history", "career history", "experience history", "past companies",
            "employers", "where did i work", "where have i worked", "companies i worked",
            "did i work", "have i worked", "worked at", "worked for", "roles held",
            "positions held", "job history", "career scan"
        ]
        is_work_q = any(h in low for h in work_hints) or "company" in low or "employer" in low
        if not is_work_q:
            return None

        ctx = self._build_structured_context([])
        work_exp = ctx.get("work_experience", [])
        if not work_exp:
            return None

        # Check for specific company verification
        if "did i work" in low or "have i worked" in low:
            words = [re.sub(r'[^a-zA-Z0-9]', '', w) for w in low.split()]
            for j in work_exp:
                c_low = j["company"].lower()
                if any(w in c_low for w in words if len(w) >= 4 and w not in ["work", "worked", "working", "company", "where", "have"]):
                    date_str = f" from {j['dates']}" if j.get('dates') else ""
                    ans = f"Yes — **{j['role']}** at **{j['company']}**{date_str}."
                    parent = next((c for c in self.vector_store.get_all() if c.get("is_parent")==1 and j["company"].lower() in (c.get("company","") or c.get("title","")).lower()), None)
                    chunks = [{"chunk_id": parent["chunk_id"], "title": parent.get("title","")[:80], "content": parent["content"][:800]}] if parent else []
                    return {"answer": ans, "chunks": chunks, "company_matched": True}
            comps = [j["company"] for j in work_exp]
            ans = f"No — your resume lists experience at **{', '.join(comps)}**."
            return {"answer": ans, "chunks": [], "company_matched": False}

        # General work history summary
        lines = []
        for j in work_exp:
            d_str = f" ({j['dates']})" if j.get('dates') else ""
            lines.append(f"• **{j['role']}** at **{j['company']}**{d_str}")
        ans = "### 💼 Work History\n" + "\n".join(lines)
        parents = [c for c in self.vector_store.get_all() if c.get("is_parent")==1 and any(j["company"].lower() in (c.get("company","") or c.get("title","")).lower() for j in work_exp)]
        chunks = [{"chunk_id": p["chunk_id"], "title": p.get("title","")[:80], "content": p["content"][:800]} for p in parents[:3]]
        return {"answer": ans, "chunks": chunks, "jobs": work_exp}

    def _skills_structured(self, q: str) -> dict | None:
        low = q.lower()
        if not any(w in low for w in ["skill","tool"]):
            return None
        if "summarize" not in low and "list" not in low and "what are" not in low:
            return None
        try:
            pp = get_user_profile_path(self.user_id)
            if pp.exists():
                prof = json.loads(pp.read_text(encoding="utf-8"))
            else:
                from candidate_profile import load_candidate_profile
                prof = load_candidate_profile()
            skills = prof.get("resume_facts",{}).get("skills","")
            is_garbled = skills and ("pipeline" in skills.lower() and len(skills) > 100 or "Designed data pipelines" in skills)
            if skills and skills != "NEEDS_REVIEW" and len(skills.split(",")) >= 3 and not is_garbled:
                return {"answer": f"Core skills: {skills[:600]}", "skills": skills}
            all_chunks = self.vector_store.get_all()
            sks = []
            for c in all_chunks:
                try:
                    s = json.loads(c.get("skills","[]"))
                    sks.extend(s)
                except Exception:
                    pass
            uniq = sorted(set(sks))
            if uniq:
                return {"answer": f"Core skills: {', '.join(uniq[:12])}", "skills": uniq}
        except Exception:
            pass
        return None

    def _metrics_structured(self, q: str) -> dict | None:
        low = q.lower()
        if not any(w in low for w in ["metric","revenue","leadership","quantified","achievement"]):
            return None
        try:
            all_chunks = self.vector_store.get_all()
            metrics = []
            for c in all_chunks:
                try:
                    m = json.loads(c.get("metrics","[]"))
                    metrics.extend(m)
                except Exception:
                    pass
            uniq = []
            seen = set()
            for m in metrics:
                if m not in seen:
                    seen.add(m)
                    uniq.append(m)
            if not uniq:
                return None
            ans = f"Key metrics: {', '.join(uniq[:12])}"
            parent = next((c for c in all_chunks if c.get("is_parent")==1 and c.get("metrics") and len(json.loads(c.get("metrics","[]")))>0), None)
            chunk_ref = [{"chunk_id": parent["chunk_id"], "title": parent.get("title","")[:80], "content": parent["content"][:800]}] if parent else []
            return {"answer": ans, "metrics": uniq, "chunks": chunk_ref}
        except Exception:
            return None

    def _jd_match_analysis(self, jd_text: str) -> Dict[str, Any]:
        all_chunks = self.vector_store.get_all()
        retrieved = self.retriever.retrieve(jd_text[:400], top_k=8)
        if not retrieved:
            retrieved = all_chunks[:6]

        context_snippets = []
        for c in retrieved:
            txt = c.get("content", "")
            if c.get("_parent") and isinstance(c["_parent"], dict):
                txt += "\n" + c["_parent"].get("content", "")[:400]
            context_snippets.append(txt)
        context_str = "\n\n---\n\n".join(context_snippets[:6])

        prompt = f"""You are an expert AI Career & Resume Match Analyzer.
Compare the Candidate Resume against the Job Description (JD) below.

CANDIDATE RESUME CONTEXT:
{context_str[:3500]}

JOB DESCRIPTION:
{jd_text[:3000]}

Produce a structured, objective evaluation in clean GitHub Markdown:

🎯 **Job Fit Analysis**: [Role Title from JD] — [Estimated Fit e.g. 75%] Match

✅ **Matched in Your Resume**:
• **[Skill/Area]**: [Specific evidence from resume]
• ...

❌ **Missing / Skill Gaps**:
• **[Missing Requirement]**: [What JD asks for that is not in resume]
• ...

💡 **Recommendation**:
[1-2 sentences on fit and how candidate can tailor or position their strengths]
"""
        try:
            from gemini_api import generate_rag_response
            ans = generate_rag_response(prompt, max_tokens=1000, timeout=8)
        except Exception:
            ans = ""

        if not ans or len(ans.strip()) < 30:
            def _extract_job_title(text: str) -> str:
                m = re.search(r'(?:Job Title|Position Title|Role Title|Title|Position)\s*[:\-]\s*([A-Za-z0-9\s\(\)\/\-\+]{3,50})', text, re.I)
                if m:
                    return m.group(1).split('\n')[0].strip()
                m2 = re.search(r'(?:Hiring for|Looking for|Role:)\s*([A-Za-z0-9\s\(\)\/\-\+]{3,50})', text, re.I)
                if m2:
                    return m2.group(1).split('\n')[0].strip()
                first_line = text.strip().split('\n')[0][:60].strip()
                if any(k in first_line.lower() for k in ["engineer", "developer", "scientist", "manager", "architect", "lead", "specialist", "consultant", "analyst"]):
                    return first_line
                if "wso2" in text.lower():
                    return "WSO2 / DevOps Specialist"
                return "Job Description Analysis"

            job_title = _extract_job_title(jd_text)
            
            terms = [
                ('Python', ['python', 'py']),
                ('Machine Learning / AI', ['machine learning', 'ml', 'ai', 'statistical model', 'forecasting', 'clustering', 'regression', 'classification']),
                ('Deep Learning & LLMs', ['llm', 'deep learning', 'pytorch', 'tensorflow', 'lora', 'gemma', 'transformers', 'rag', 'langchain', 'chromadb', 'haystack']),
                ('Docker & Containers', ['docker', 'dockerized', 'container', 'containerization', 'kubernetes']),
                ('CI/CD & MLOps', ['ci/cd', 'mlops', 'pipeline', 'observability', 'grafana', 'prometheus', 'langfuse']),
                ('Cloud (AWS/Azure/GCP)', ['aws', 'azure', 'gcp', 'google cloud', 'databricks', 'airflow']),
                ('Git & Version Control', ['git', 'github', 'version control']),
                ('WSO2 & Integration', ['wso2', 'esb', 'api manager']),
                ('Linux & OS', ['linux', 'unix', 'ubuntu']),
                ('Databases & SQL', ['sql', 'postgresql', 'mongodb', 'database'])
            ]
            
            resume_text = (' '.join(c.get('content', '') for c in all_chunks) + ' ' + context_str).lower()
            
            matched = []
            missing = []
            for label, syns in terms:
                in_jd = any(re.search(r'\b' + re.escape(s) + r'\b', jd_text.lower()) for s in syns)
                if in_jd:
                    in_resume = any(s in resume_text for s in syns)
                    if in_resume:
                        matched.append(label)
                    else:
                        missing.append(label)
            
            total_reqs = len(matched) + len(missing) or 1
            fit_pct = int(round((len(matched) / total_reqs) * 100))
            
            m_bullets = '\n'.join(f'• **{m}**: Supported by candidate experience and projects' for m in matched) if matched else '• *No direct technical keyword overlap found*'
            g_bullets = '\n'.join(f'• **{g}**: Required by JD but not explicitly highlighted in resume' for g in missing) if missing else '• *No significant skill gaps identified!*'
            
            ans = f"""🎯 **Job Fit Analysis**: {job_title} — ~{fit_pct}% Match

### ✅ Matched in Your Resume:
{m_bullets}

### ❌ Missing / Skill Gaps:
{g_bullets}

### 💡 Recommendation:
{"Strong alignment on core engineering competencies. Highlight your matched projects when answering screening questions." if fit_pct >= 50 else "Moderate match. Focus on transferable fundamentals and highlight any related coursework or project work."}"""

        return {
            "answer": ans,
            "route": "MULTI_DOC",
            "domain": "jd",
            "cached": "L3",
            "verified": True,
            "chunks": retrieved,
            "reason": "jd_semantic_match"
        }

    def query(self, q: str, scope: str = "auto", use_cache: bool = True, verify: bool = True) -> Dict[str, Any]:
        self._ensure_index()
        t0 = time.time()
        route = classify_query(q)

        # Tier 1: Check L1 Exact & L2 Semantic Cache (<5ms)
        if use_cache:
            hit = self.cache.get(q)
            if hit:
                return {
                    "answer": hit["answer"],
                    "route": route.target.value,
                    "domain": route.domain,
                    "cached": hit["tier"],
                    "verified": hit["answer"] != "NEEDS_REVIEW",
                    "chunks": [],
                    "reason": "semantic_cache_hit",
                    "matched_q": hit.get("matched_q"),
                    "latency_ms": max(1, int((time.time() - t0) * 1000))
                }

        # Tier 2: Domain-specific structured fast-paths (0ms LLM cost)
        if route.domain == "reports":
            structured = self._reports_structured(route.rewritten_query)
            if structured is not None:
                ans = structured["answer"]
                chunks = [{"chunk_id": "visited.json", "title": "visited.json", "content": json.dumps(structured.get("by_status",{}))[:800]}]
                if use_cache:
                    try: self.cache.put(q, ans)
                    except Exception: pass
                return {"answer": ans, "route": route.target.value, "domain": "reports", "cached": "direct", "verified": True, "chunks": chunks, "reason": "structured_reports", "latency_ms": int((time.time()-t0)*1000)}

        # Work history / past companies check
        w_struct = self._work_history_structured(route.rewritten_query)
        if w_struct is not None:
            ans = w_struct["answer"]
            chunks = w_struct.get("chunks", [])
            if use_cache:
                try: self.cache.put(q, ans)
                except Exception: pass
            return {"answer": ans, "route": route.target.value, "domain": "resume", "cached": "direct", "verified": True, "chunks": chunks, "reason": "structured_work_history", "latency_ms": int((time.time()-t0)*1000)}

        if route.domain == "chunks":
            m_struct = self._metrics_structured(route.rewritten_query)
            if m_struct is not None:
                ans = m_struct["answer"]
                chunks = m_struct.get("chunks") or []
                if not chunks:
                    chunks = self.retriever.retrieve(route.rewritten_query, top_k=3)
                if use_cache:
                    try: self.cache.put(q, ans)
                    except Exception: pass
                return {"answer": ans, "route": route.target.value, "domain": "chunks", "cached": "direct", "verified": True, "chunks": chunks, "reason": "structured_metrics", "latency_ms": int((time.time()-t0)*1000)}

        if route.domain == "profile":
            p_struct = self._profile_structured(route.rewritten_query)
            if p_struct is not None:
                ans = p_struct["answer"]
                if use_cache:
                    try: self.cache.put(q, ans)
                    except Exception: pass
                return {"answer": ans, "route": route.target.value, "domain": "profile", "cached": "direct", "verified": True, "chunks": [], "reason": "structured_profile", "latency_ms": int((time.time()-t0)*1000)}

        if route.domain == "resume":
            s_struct = self._skills_structured(route.rewritten_query)
            if s_struct is not None:
                ans = s_struct["answer"]
                if use_cache:
                    try: self.cache.put(q, ans)
                    except Exception: pass
                return {"answer": ans, "route": route.target.value, "domain": "resume", "cached": "direct", "verified": True, "chunks": [], "reason": "structured_skills", "latency_ms": int((time.time()-t0)*1000)}

        if route.domain == "jd":
            jd_res = self._jd_match_analysis(route.rewritten_query)
            if use_cache and jd_res.get("answer"):
                try: self.cache.put(q, jd_res["answer"])
                except Exception: pass
            jd_res["latency_ms"] = int((time.time() - t0) * 1000)
            return jd_res

        # Atomic key direct lookup
        if route.target == RouteTarget.SINGLE_DOC:
            direct = self._direct_lookup(route.rewritten_query, route.target_key, route.domain)
            if direct is not None and direct != "NEEDS_REVIEW":
                if use_cache:
                    try: self.cache.put(q, direct)
                    except Exception: pass
                return {"answer": direct, "route": route.target.value, "domain": route.domain, "cached": "direct", "verified": True, "chunks": [], "reason": route.reason, "latency_ms": int((time.time()-t0)*1000)}
            if direct == "NEEDS_REVIEW":
                return {"answer": "NEEDS_REVIEW", "route": route.target.value, "domain": route.domain, "cached": "direct", "verified": False, "chunks": [], "reason": "sentinel", "latency_ms": int((time.time()-t0)*1000)}

        # Tier 3: General-Purpose Structured JSON RAG with Hybrid Retrieval
        retrieved = self.retriever.retrieve(route.rewritten_query, top_k=6)
        if not retrieved:
            all_chunks = self.vector_store.get_all()
            if not all_chunks:
                return {"answer": "NEEDS_REVIEW", "route": route.target.value, "domain": route.domain, "cached": "miss", "verified": False, "chunks": [], "reason": "no_index", "latency_ms": int((time.time()-t0)*1000)}
            retrieved = [{"content": c["content"], "chunk_id": c["chunk_id"], "_parent": None} for c in all_chunks[:3]]

        structured_ctx = self._build_structured_context(retrieved)
        ctx_json_str = json.dumps(structured_ctx, indent=2, ensure_ascii=False)

        prompt = f"""You are an intelligent, truthful AI Career Assistant.
Answer the user's question using ONLY the provided structured candidate JSON context.
Be direct, clear, and professional. Use GitHub markdown formatting.

STRUCTURED CANDIDATE CONTEXT:
{ctx_json_str[:3500]}

USER QUESTION:
{q}

ANSWER:"""

        try:
            from gemini_api import generate_rag_response
            ans = generate_rag_response(prompt, max_tokens=1000, timeout=8)
        except Exception:
            ans = ""

        if not ans or len(ans.strip()) < 10:
            # Deterministic fallback from structured context
            ans = "NEEDS_REVIEW"
            verified = False
        else:
            verified = True

        if verify and ans != "NEEDS_REVIEW" and verified:
            try:
                v = verify_answer(ans, retrieved)
                if not v["verified"] and "missing" not in ans.lower():
                    ans = "NEEDS_REVIEW"
                    verified = False
            except Exception:
                pass

        if use_cache and ans != "NEEDS_REVIEW":
            try: self.cache.put(q, ans)
            except Exception: pass

        return {
            "answer": ans,
            "route": route.target.value,
            "domain": route.domain,
            "cached": "L3" if ans != "NEEDS_REVIEW" else "miss",
            "verified": verified,
            "chunks": retrieved,
            "reason": route.reason + "+structured_rag",
            "latency_ms": max(1, int((time.time()-t0)*1000))
        }

    def curate_for_jd(self, jd_text: str) -> Dict[str, Any]:
        if not jd_text or len(jd_text.strip()) < 20:
            return {"score": 0.0, "matched": [], "missing": [], "tailored": None}
        try:
            from resume.scorer import score_jd_vs_resume
            from resume.curator import curate_md
            from pathlib import Path
            base_md = ""
            for cand in [self.shard / "resumes" / "base.md", Path("resumes/base.md")]:
                if cand.exists():
                    base_md = cand.read_text(encoding="utf-8", errors="ignore")
                    break
            scored = score_jd_vs_resume(jd_text, base_md)
            gaps = scored.get("missing", [])
            try:
                from web.db import record_jd as _rjd
                jh = _rjd(self.user_id, "", "", "", jd_text)
            except Exception:
                jh = None
            try:
                from resume.review_loop import run_tailor_loop
                from web.db import record_tailor_run as _rtr
                loop = run_tailor_loop(self.user_id, jd_text, base_md)
                trid = _rtr(self.user_id, jh, loop.get("verdict", "fail_open"), loop.get("best_score", 0.0),
                            {"matched": scored.get("matched", []), "missing": gaps}, loop.get("attempts", [])) if loop.get("attempts") else None
                if loop.get("final_md"):
                    return {"score": scored.get("score"), "matched": scored.get("matched"), "missing": gaps,
                            "tailored": loop["final_md"][:8000], "jd_hash": jh, "tailor_run_id": trid,
                            "loop": {"verdict": loop["verdict"], "attempts": loop["attempts"], "best_score": loop["best_score"]}}
            except Exception as e:
                print(f"[rag] tailor loop warn {e}")
            if gaps and len(gaps) >= 2:
                retrieved = self.retriever.retrieve(" ".join(gaps[:4]), top_k=3)
                context = "\n".join(d.get("content","") for d in retrieved)
                cur = curate_md(base_md, jd_text + f"\n\nEmphasize: {context[:2000]}")
            else:
                cur = curate_md(base_md, jd_text)
            return {"score": scored.get("score"), "matched": scored.get("matched"), "missing": gaps, "tailored": cur[:8000], "jd_hash": jh, "tailor_run_id": None}
        except Exception as e:
            return {"error": str(e)[:300]}

    def get_stats(self) -> Dict[str, Any]:
        return {"user_id": self.user_id, "chunks": self.vector_store.count(), "qa_cached": self.cache.count(), "shard": str(self.shard)}

    def invalidate(self):
        self.cache.clear()
        invalidate_manager(self.user_id)

    def rebuild_index(self) -> Dict[str, Any]:
        for cand in [self.shard / "resumes" / "base.md", Path("resumes/base.md")]:
            if cand.exists():
                return self.ingest_file(cand)
        return {"error": "no base.md found"}
