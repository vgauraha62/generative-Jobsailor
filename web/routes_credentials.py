import json, os, zipfile
from pathlib import Path
from fastapi import APIRouter, Request, Depends, HTTPException, UploadFile, File
from web.auth import require_auth
from web.per_user import shard, get_user_shard

router = APIRouter(prefix="/api/credentials")

def _load_user_config(uid):
    p = shard(uid) / "config.json"
    if p.exists():
        try: return json.loads(p.read_text())
        except: pass
    # defaults
    return {"search":{"slugs":[]},"browser":{"profile_path":"", "binary":"/opt/firefox/firefox"},"gemini":{"model":"gemini-2.0-flash"},"resume_curation":{"threshold":0.5}}

@router.get("")
async def get_credentials(request: Request, _=Depends(require_auth)):
    uid = request.session.get("user_id")
    if not uid: raise HTTPException(status_code=401, detail="Not authenticated")
    cfg = _load_user_config(uid)
    profile = {}
    pp = shard(uid) / "candidate_profile.json"
    if pp.exists():
        try: profile = json.loads(pp.read_text())
        except: profile = {}
    else:
        profile = {"resume_facts": {"name": "NEEDS_REVIEW", "email": "NEEDS_REVIEW", "phone": "NEEDS_REVIEW", "highest_qualification": "NEEDS_REVIEW", "institution": "NEEDS_REVIEW", "total_experience_years": "NEEDS_REVIEW", "relevant_experience_years": "NEEDS_REVIEW", "current_location": "NEEDS_REVIEW", "skills": "NEEDS_REVIEW"}, "user_preferences": {"current_ctc_lpa": "NEEDS_REVIEW", "expected_ctc_lpa": "NEEDS_REVIEW", "notice_period_days": "NEEDS_REVIEW", "willing_to_relocate": "NEEDS_REVIEW", "work_authorization": "NEEDS_REVIEW", "passport_valid": "NEEDS_REVIEW"}}
    from gemini_api import provider_for
    return {"config": cfg, "profile": profile, "provider": provider_for(uid)}

@router.post("")
async def save_credentials(request: Request, _=Depends(require_auth)):
    uid = request.session.get("user_id")
    if not uid: raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        data = await request.json()
    except: raise HTTPException(status_code=400, detail="Invalid JSON")
    slugs = data.get("slugs") or []
    profile_path = (data.get("profile_path") or "").strip()
    gemini_key = (data.get("gemini_key") or "").strip()
    gemini_model = (data.get("gemini_model") or "").strip()
    profile = data.get("profile")
    profile_json = data.get("profile_json") or ""
    # support both new per-field profile object and old profile_json string
    if profile and isinstance(profile, dict):
        pj = profile
    elif profile_json:
        try: pj = json.loads(profile_json)
        except: raise HTTPException(status_code=400, detail="Invalid profile JSON")
    else:
        pj = None
    if slugs:
        import re
        for s in slugs:
            if not re.match(r"^[a-z0-9\-]+$", s.replace("-jobs","")):
                raise HTTPException(status_code=400, detail=f"invalid slug {s}")
    if pj is not None:
        pp = shard(uid) / "candidate_profile.json"
        tmp2 = pp.with_suffix(".tmp")
        tmp2.write_text(json.dumps(pj, indent=2))
        tmp2.replace(pp)
        # also upsert to sql
        try:
            from web.db import _conn
            conn = _conn()
            conn.execute("INSERT OR REPLACE INTO candidate_profiles (user_id, profile_json) VALUES (?,?)", (uid, json.dumps(pj)))
            conn.commit(); conn.close()
        except: pass
    cfg = _load_user_config(uid)
    cfg["search"]["slugs"] = slugs
    cfg["browser"]["profile_path"] = profile_path
    if gemini_model:
        cfg["gemini"]["model"] = gemini_model
    gem_file = shard(uid) / ".env.gemini"
    if gemini_key:
        gem_file.write_text(f"GEMINI_API_KEY={gemini_key}\nGEMINI_MODEL={gemini_model}\n")
    elif gem_file.exists():
        # ponytail: empty key field reverts to free pool; strip owned-key lines only
        kept = [l for l in gem_file.read_text().splitlines() if not l.startswith(("GEMINI_API_KEY=", "GEMINI_MODEL="))]
        gem_file.write_text("\n".join(kept) + ("\n" if kept else ""))
    p = shard(uid) / "config.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    tmp.replace(p)
    try:
        from web.db import _conn
        conn = _conn()
        conn.execute("INSERT OR REPLACE INTO configs (user_id, raw_json) VALUES (?,?)", (uid, json.dumps(cfg)))
        conn.commit(); conn.close()
    except: pass
    try:
        from web.per_user import record_audit
        record_audit(uid, "credentials_save", {"slugs": slugs, "own_key": bool(gemini_key), "model": gemini_model or None})
    except Exception:
        pass
    return {"ok": True}

def _extract_facts_pytesseract(raw: str, filename: str = ""):
    import re, os, datetime
    facts = {}
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    top_lines = lines[:25]
    bottom_lines = lines[-20:] if len(lines) > 20 else lines
    # ponytail: other-people zones never yield the candidate's name (declaration signature IS the candidate)
    _QHEAD = re.compile(r'^\s*(references|family|family details|nominee|emergency contact)\b', re.I)
    _NHEAD = re.compile(r'^[A-Z][A-Z\s&/\-]{3,}:?\s*$')
    qset, _qs = set(), None
    for _qi, _ql in enumerate(lines):
        if _QHEAD.match(_ql):
            _qs = _qi
        elif _NHEAD.match(_ql) and _qs is not None and _qi > _qs:
            _qs = None
        if _qs is not None:
            qset.add(_qi)
    qtexts = {lines[_i] for _i in qset}

    # 1. Email (direct, [at]/[dot] de-obfuscation, full text)
    m_email = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', raw)
    if not m_email:
        deob = re.sub(r'\s*\[\s*(at|@)\s*\]\s*', '@', raw, flags=re.I)
        deob = re.sub(r'\s*\[\s*(dot|\.)\s*\]\s*', '.', deob, flags=re.I)
        deob = re.sub(r'\s+\b(at)\b\s+', '@', deob, flags=re.I)
        deob = re.sub(r'\s+\b(dot)\b\s+', '.', deob, flags=re.I)
        m_email = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', deob)
    if m_email:
        facts["email"] = m_email.group(0).strip().lower()

    # 2. Phone (whitespace-normalized; every candidate kept, anchor-nearest wins)
    flat = re.sub(r'\s+', ' ', raw)
    anchor = flat.find(facts.get("email", "\0"))
    def _clean_phone(p):
        c = re.sub(r'[^\d+]', '', p.strip())
        if c.startswith('+91') and len(c) == 13:
            return c[3:]
        c = c.lstrip('+')
        if len(c) == 10 and c.isdigit():
            return c
        if len(c) > 10 and c.isdigit():
            return c[-10:]
        return ""
    cands = []
    for pat in (r'(?:\+?91[\s\-.]?)?[6-9]\d{4}[\s\-.]?\d{5}\b', r'(?:\+?91[\s-]?)?[6-9]\d{9}\b', r'(?:\+\d{1,3}[\s-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b'):
        for m in re.finditer(pat, flat):
            c = _clean_phone(m.group(0))
            if c and c not in [x[0] for x in cands]:
                cands.append((c, abs(m.start() - anchor) if anchor >= 0 else 0))
    if cands:
        facts["phone"] = sorted(cands, key=lambda x: x[1])[0][0]
        if len(cands) > 1:
            facts["_phone_candidates"] = [c for c, _ in cands]  # trace only, never merged

    # 3. Name - 3 robust deterministic tiers
    non_name_keywords = {
        'resume', 'curriculum', 'vitae', 'cv', 'profile', 'bio', 'summary', 'contact',
        'email', 'phone', 'page', 'http', 'github', 'linkedin', 'portfolio', 'engineer',
        'developer', 'scientist', 'manager', 'lead', 'architect', 'analyst', 'intern',
        'snapshot', 'competency', 'competencies', 'areas', 'expertise', 'career', 'scan',
        'experience', 'education', 'qualification', 'qualifications', 'personal', 'details',
        'address', 'declaration', 'place', 'date', 'role', 'objective', 'wife', 'husband',
        'father', 'mother', 'spouse', 'son', 'daughter', 'w/o', 's/o', 'd/o', 'nominee',
        'emergency', 'reference', 'references', 'referee', 'married', 'children', 'dependent',
        'guardian', 'parents', 'family', 'contact-person'
    }

    # 3a: Contact-anchor neighborhood first (name sits next to email/phone), then top lines
    anchor_idx = None
    for _i, _l in enumerate(lines):
        if facts.get("email") and facts["email"] in _l.lower():
            anchor_idx = _i
            break
    if anchor_idx is None and facts.get("phone"):
        _dg = re.sub(r'\D', '', facts["phone"])
        for _i, _l in enumerate(lines):
            if _dg and _dg in re.sub(r'\D', '', _l):
                anchor_idx = _i
                break
    _probe = [(l, 1) for l in top_lines[:10] if l not in qtexts]
    if anchor_idx is not None:
        _idx = sorted(range(max(0, anchor_idx - 3), min(len(lines), anchor_idx + 4)), key=lambda i: (abs(i - anchor_idx), i))
        _seen, _near = set(), []
        for _i in _idx:
            if _i in qset or lines[_i] in _seen:
                continue
            _seen.add(lines[_i])
            _near.append((lines[_i], 2))  # near-anchor candidates need 2+ words (skips "Pune" residue)
        _probe = _near + [(l, 1) for l in top_lines[:10] if l not in qtexts]  # ponytail: near lines re-evaluated leniently; strict pass runs first so order is safe
    for line, _minw in _probe:
        if any(h in line.upper() for h in ['SNAPSHOT:', 'SUMMARY:', 'OBJECTIVE:', 'CORE COMPETENC', 'AREAS OF EXPERTISE', 'EXPERIENCE:']):
            break
        line = re.sub(r'\S+@\S+', '', line)
        line = re.sub(r'\+?[\d][\d\s\-.()]{7,}\d', '', line)
        if 'http' in line:
            continue
        cleaned_line = re.sub(r'[\(\[\{].*?[\)\]\}]', '', line)
        cleaned_line = re.sub(r'\b(?:Dr\.|Dr|Mr\.|Mr|Ms\.|Ms|Mrs\.|Mrs|Prof\.|Prof|Ph\.?D\.?)\b', '', cleaned_line, flags=re.I)
        cleaned_line = re.split(r'\s+[\|\-–•·]\s+', cleaned_line)[0].strip()
        cleaned_line = re.sub(r'[^a-zA-Z\s\.\'-]', '', cleaned_line).strip(' ,.-')
        words = cleaned_line.split()
        if _minw <= len(words) <= 4 and 3 <= len(cleaned_line) <= 40:
            if not any(w.lower() in non_name_keywords for w in words):
                if all(w[0].isupper() or w.isupper() for w in words if len(w) > 1):
                    facts["name"] = cleaned_line.title() if cleaned_line.isupper() else cleaned_line
                    break

    # 3b: Signature at bottom of resume (e.g. Place: Pune ... Date: ... Name)
    if "name" not in facts:
        for line in reversed(bottom_lines):
            if line in qtexts:
                continue
            if not re.search(r'(?:Name|Signature|Date)\s*[:\-]', line, flags=re.I):
                continue  # ponytail: Place values are locations, not names; prefix must match
            cleaned_line = re.sub(r'[\(\[\{].*?[\)\]\}]', '', line)
            cleaned_line = re.sub(r'.*?(?:Name|Signature|Date)\s*[:\-]\s*', '', cleaned_line, flags=re.I).strip()
            cleaned_line = re.sub(r'[^a-zA-Z\s\.\'-]', '', cleaned_line).strip(' ,.-')
            words = cleaned_line.split()
            if 2 <= len(words) <= 3 and 4 <= len(cleaned_line) <= 35:
                if not any(w.lower() in non_name_keywords for w in words):
                    if all(w[0].isupper() or w.isupper() for w in words if len(w) > 1):
                        facts["name"] = cleaned_line.title() if cleaned_line.isupper() else cleaned_line
                        break

    # 3c: From original filename (e.g. Resume_Awnish sharma_updated.docx -> Awnish Sharma)
    if "name" not in facts and filename:
        clean_fn = os.path.splitext(os.path.basename(filename))[0]
        clean_fn = re.sub(r'(?i)\b(?:resume|cv|updated|latest|profile|final|new|draft)\b', '', clean_fn)
        clean_fn = re.sub(r'[_\-\.\+]+', ' ', clean_fn).strip()
        words = clean_fn.split()
        if 1 <= len(words) <= 3 and all(len(w) >= 2 for w in words):
            if not any(w.lower() in non_name_keywords for w in words):
                facts["name"] = clean_fn.title()

    # 4. Current Location
    cities = ['Bengaluru', 'Bangalore', 'Hyderabad', 'Pune', 'Mumbai', 'Delhi', 'Noida', 'Gurgaon', 'Gurugram', 'Chennai', 'Kolkata', 'Ahmedabad', 'Jaipur', 'Bhilai', 'Raipur', 'Indore', 'Bhopal', 'Chandigarh', 'Kochi', 'Coimbatore', 'San Francisco', 'New York', 'Seattle', 'Austin', 'Boston', 'London', 'Singapore', 'Toronto', 'Chicago']
    m_addr = re.search(r'(?:Contact Address|Permanent Address|Current Address|Address|Location|City|Place)\s*[:\-]\s*([A-Za-z0-9\s,.\-\/]{3,80})', raw, re.I)
    if m_addr:
        cand_addr = m_addr.group(1).split('\n')[0].strip(' ,.-')
        for city in cities:
            if re.search(r'\b' + re.escape(city) + r'\b', cand_addr, re.I):
                m_match = re.search(r'\b(' + re.escape(city) + r'(?:\s*,\s*[A-Za-z\s]+)?)\b', cand_addr, re.I)
                if m_match:
                    facts["current_location"] = m_match.group(1).strip()
                    break
        if "current_location" not in facts and len(cand_addr) <= 40:
            facts["current_location"] = cand_addr

    if "current_location" not in facts:
        for line in top_lines:
            for city in cities:
                if re.search(r'\b' + re.escape(city) + r'\b', line, re.I):
                    cand = line.strip()
                    cand = re.sub(r'[\(\[\{].*?[\)\]\}]', '', cand)
                    cand = re.sub(r'[^a-zA-Z\s,.-]', '', cand).strip(' ,.-')
                    if cand and not any(k in cand.lower() for k in ['github', 'linkedin', 'http', '@']):
                        facts["current_location"] = cand[:50]
                        break
            if "current_location" in facts:
                break

    # 5. Highest Qualification (hierarchical check including MA, BA, etc.)
    degrees = [
        (r'\b(Ph\.?D|Doctorate|Doctor of Philosophy)\b', 'PhD'),
        (r'\b(M\.?Tech(?:nology)?|Master of Technology)\b', 'MTech'),
        (r'\b(M\.?E\.?|Master of Engineering)\b', 'ME'),
        (r'\b(M\.?S\.?(?:ci)?|Master of Science)\b', 'MS'),
        (r'\b(M\.?A\.?(?:\s+in\s+[A-Za-z]+)?|Master of Arts)\b', 'MA'),
        (r'\b(M\.?C\.?A\.?|Master of Computer Applications)\b', 'MCA'),
        (r'\b(M\.?B\.?A\.?|Master of Business Administration|PGDM)\b', 'MBA'),
        (r'\b(M\.?Sc\.?)\b', 'MSc'),
        (r'\b(M\.?Com\.?)\b', 'MCom'),
        (r'\b(B\.?Tech(?:nology)?|Bachelor of Technology)\b', 'BTech'),
        (r'\b(B\.?E\.?|Bachelor of Engineering)\b', 'BE'),
        (r'\b(B\.?S\.?(?:ci)?|Bachelor of Science)\b', 'BS'),
        (r'\b(B\.?A\.?(?:\s+classic)?|Bachelor of Arts)\b', 'BA'),
        (r'\b(B\.?C\.?A\.?|Bachelor of Computer Applications)\b', 'BCA'),
        (r'\b(B\.?B\.?A\.?|Bachelor of Business Administration)\b', 'BBA'),
        (r'\b(B\.?Sc\.?)\b', 'BSc'),
        (r'\b(B\.?Com\.?)\b', 'BCom'),
        (r'\b(Bachelor(?:\'s)?\s+Degree|Master(?:\'s)?\s+Degree)\b', 'Bachelor'),
        (r'\b(Diploma(?:\s+in\s+[A-Za-z\s]+)?)\b', 'Diploma'),
    ]
    for pattern, deg_name in degrees:
        if re.search(pattern, raw, re.I):
            facts["highest_qualification"] = deg_name
            break

    # 6. Institution - Look in Education / Academic section first
    edu_sec = re.search(r'(?:EDUCATION|ACADEMIC|QUALIFICATION|EXTRAMURAL\s+ENGAGEMENTS)[\s\:\-\n]+(.*?)(?=\n\s*(?:EXPERIENCE|CAREER|PROFESSIONAL|PERSONAL\s+DETAILS|ACHIEVEMENTS|AWARDS|\Z))', raw, re.I | re.DOTALL)
    search_text_inst = edu_sec.group(1) if edu_sec else raw

    inst_patterns = [
        r'\b((?:Indian Institute of Technology|National Institute of Technology|Indian Institute of Information Technology|Birla Institute of Technology|IIT|NIT|IIIT|BITS|MIT|IISc|IIM)\s+[A-Za-z]+)\b',
        r'\b((?:University|College|Institute|Academy)\s+of\s+[A-Za-z\s&,\.]{2,40})\b',
        r'\b([A-Z][A-Za-z\s&,\.]{2,40}\s+(?:University|Institute of Technology|College of Engineering|Institute|College|Academy|Polytechnic))\b',
    ]
    for ip in inst_patterns:
        m_inst = re.search(ip, search_text_inst)
        if m_inst:
            cand = m_inst.group(1).strip()
            cand = re.sub(r'[\(\[\{].*?[\)\]\}]', '', cand).strip()
            cand = re.sub(r'[\d\-–,\.]+$', '', cand).strip()
            if not any(stop in cand.lower() for stop in ['client', 'project', 'delivering', 'worked', 'outcome', 'developed', 'launch', 'programs', 'activity']):
                facts["institution"] = cand[:60]
                break

    # 7. Experience Years
    m_exp = re.search(r'(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)(?:\s+of)?(?:\s+(?:relevant|total|professional|industry|hands-on))?\s+experience\b', raw, re.I)
    if m_exp:
        try:
            val = float(m_exp.group(1))
            facts["total_experience_years"] = int(val) if val.is_integer() else val
            facts["relevant_experience_years"] = facts["total_experience_years"]
        except: pass
    else:
        year_spans = re.findall(r'\b(20[0-2]\d)\s*(?:-|–|to)\s*(20[0-2]\d|Present|Current)\b', raw, re.I)
        if year_spans:
            cur_year = datetime.datetime.now().year
            total_calc = 0
            for start_y, end_y in year_spans:
                s = int(start_y)
                e = cur_year if end_y.lower() in ('present', 'current') else int(end_y)
                diff = max(0, e - s)
                if 0 < diff <= 30:
                    total_calc += diff
            if total_calc > 0:
                facts["total_experience_years"] = min(total_calc, 30)
                facts["relevant_experience_years"] = facts["total_experience_years"]

    # 8. Skills - Search for Core Competencies, Areas of Expertise, or Technical Skills
    skills_sec = re.search(r'(?:CORE\s+COMPETENC(?:Y|IES)|AREAS?\s+OF\s+EXPERTISE|TECHNICAL\s+SKILLS|KEY\s+SKILLS|KEY\s+COMPETENC(?:Y|IES)|SKILLS\s*&?\s*EXPERTISE|SKILLS|TECHNOLOGIES|TECH\s+STACK)[\s\:\-\n]+(.*?)(?=\n\s*(?:CAREER\s+SCAN|PROFESSIONAL\s+EXPERIENCE|EXPERIENCE|WORK\s+EXPERIENCE|EMPLOYMENT|EDUCATION|PROJECTS|CERTIFICATIONS|PERSONAL\s+DETAILS|EXTRAMURAL|ACHIEVEMENTS|\Z))', raw, re.I | re.DOTALL)
    if skills_sec:
        s_text = skills_sec.group(1).strip()
        s_lines = [l.strip() for l in s_text.splitlines() if l.strip()][:15]
        cleaned_skills = []
        stop_headers = ['CAREER SCAN', 'KEY ACHIEVEMENTS', 'PERSONAL DETAILS', 'EXTRAMURAL', 'ACADEMIC', 'EDUCATION', 'EXPERIENCE', 'AREAS OF EXPERTISE', 'CORE COMPETENCY', 'TECHNICAL SKILLS']
        for sl in s_lines:
            if any(sl.upper().startswith(h) for h in stop_headers):
                continue
            sl_clean = re.sub(r'^[A-Za-z\s&/]+:\s*', '', sl)
            sl_clean = re.sub(r'^[\*\-•·\d\.\)]\s*', '', sl_clean)
            if sl_clean and len(sl_clean) > 2 and not any(k in sl_clean.lower() for k in ['father name', 'mother name', 'date of birth', 'hobbies', 'contact address']):
                cleaned_skills.append(sl_clean)
        res_skills = ', '.join(cleaned_skills)
        if len(res_skills) > 5:
            facts["skills"] = res_skills[:400]

    if not facts.get("skills"):
        keywords = ['Python', 'Java', 'C++', 'JavaScript', 'TypeScript', 'React', 'Node.js', 'Go', 'Golang', 'Rust', 'Docker', 'Kubernetes', 'AWS', 'GCP', 'Azure', 'SQL', 'PostgreSQL', 'MongoDB', 'Redis', 'Machine Learning', 'Deep Learning', 'PyTorch', 'TensorFlow', 'NLP', 'LLM', 'LangChain', 'FastAPI', 'Django', 'Flask', 'CI/CD', 'Git', 'Linux', 'Microservices', 'Spring Boot', 'Sales', 'P&L Management', 'Business Development', 'Telecom', 'Marketing']
        found = [k for k in keywords if re.search(r'\b' + re.escape(k) + r'\b', raw, re.I)]
        if found:
            facts["skills"] = ', '.join(found[:15])

    return facts


@router.post("/resume")
async def upload_resume(request: Request, file: UploadFile = File(...), _=Depends(require_auth)):
    uid = request.session.get("user_id")
    if not uid: raise HTTPException(status_code=401, detail="Not authenticated")
    data = await file.read()
    if len(data) > 10*1024*1024:
        raise HTTPException(status_code=400, detail="File too large >10MB")
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    shard_path = shard(uid)
    resumes = shard_path / "resumes"
    resumes.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename).suffix.lower() or ".pdf"
    dest = resumes / f"base{ext}"
    dest.write_bytes(data)
    ocr_facts = {}
    merged = None
    raw = ""
    raw_initial = ""
    needs_ocr_val = False
    ocr_attempted = False
    ocr_success = False
    ocr_error = None
    md_chars = 0
    md_sha = ""
    from resume.ingest import _normalize_to_md
    # snapshot before merge for per-field diff
    before_profile = {}
    try:
        pp_check = shard_path / "candidate_profile.json"
        if pp_check.exists():
            try: before_profile = json.loads(pp_check.read_text())
            except: before_profile = {}
    except: before_profile = {}
    try:
        if ext == ".pdf":
            from resume.ingest import _extract_pdf_text_pymupdf, _ocr_pdf_via_pymupdf, _needs_ocr
            try: raw_initial = _extract_pdf_text_pymupdf(str(dest))
            except Exception as e: raw_initial = ""
            raw = raw_initial
            needs_ocr_val = not raw or _needs_ocr(raw)
            if needs_ocr_val:
                ocr_attempted = True
                try:
                    raw = _ocr_pdf_via_pymupdf(str(dest))
                    ocr_success = bool(raw and raw.strip())
                except Exception as e:
                    ocr_error = str(e)[:300]
                    if not raw_initial:
                        raise HTTPException(status_code=422, detail=f"PDF needs OCR but tesseract failed: {e}. Ensure tesseract-ocr installed.")
        elif ext in (".docx", ".doc"):
            from resume.ingest import _extract_docx
            try: raw = _extract_docx(str(dest))
            except Exception as e: raise HTTPException(status_code=400, detail=f"Failed to parse docx: {e}")
        elif ext in (".txt", ".md", ".tex"):
            raw = dest.read_text(errors="ignore")[:8000]
        else:
            raise HTTPException(status_code=400, detail="Unsupported file type. Use pdf, docx, doc, txt, md")
        if not raw or not raw.strip():
            raise HTTPException(status_code=422, detail="Could not extract text from file. Try another file.")
        md = _normalize_to_md(raw, file.filename)
        md_path = shard_path / "resumes" / "base.md"
        md_path.write_text(md)
        md_chars = len(md)
        import hashlib
        md_sha = hashlib.sha256(md.encode()).hexdigest()[:12]
        ocr_facts = _extract_facts_pytesseract(raw, filename=file.filename)
        if ext == ".pdf" and not all(ocr_facts.get(k) for k in ("name", "email", "phone")):
            # ponytail: targeted OCR second pass, page 1 only — full-doc OCR runs above only when text layer is empty
            try:
                from resume.ingest import ocr_page as _ocr_page
                _f2 = _extract_facts_pytesseract(_ocr_page(str(dest)), filename=file.filename)
                for k in ("name", "email", "phone"):
                    if not ocr_facts.get(k) and _f2.get(k):
                        ocr_facts[k] = _f2[k]
                ocr_facts["_ocr_second_pass"] = {k: bool(_f2.get(k)) for k in ("name", "email", "phone")}
            except Exception as e:
                print(f"[resume] second-pass ocr warn {e}")
        pp = shard_path / "candidate_profile.json"
        existing = {}
        if pp.exists():
            try: existing = json.loads(pp.read_text())
            except: existing = {}
        if not existing:
            existing = {"resume_facts": {}, "user_preferences": {}}
        before_for_diff = json.loads(json.dumps(existing))
        existing.setdefault("user_preferences", {})
        all_keys = ["name","email","phone","highest_qualification","institution","total_experience_years","relevant_experience_years","current_location","skills"]
        # ponytail: upload is the source of truth; the form corrects, never preserves
        new_resume_facts = {}
        for k in all_keys:
            new_resume_facts[k] = ocr_facts.get(k) or "NEEDS_REVIEW"
        # ponytail: upload rewrites resume_facts only; user_preferences are manual-only, never OCR-touched
        existing["resume_facts"] = new_resume_facts
        tmp = pp.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        tmp.replace(pp)
        try:
            _aj = shard_path / "resumes" / "active.json"
            _ajt = _aj.with_suffix(".tmp")
            _ajt.write_text(json.dumps({"active_md": str(md_path), "active_pdf": None, "sha": md_sha}))
            _ajt.replace(_aj)
        except Exception:
            pass
        try:
            from web.db import _conn
            conn = _conn()
            conn.execute("INSERT OR REPLACE INTO candidate_profiles (user_id, profile_json) VALUES (?,?)", (uid, json.dumps(existing)))
            conn.commit(); conn.close()
        except: pass
        try:
            from resume.rag.manager import get_manager
            get_manager(uid).ingest_resume(md, filename=file.filename)
        except Exception as e:
            print(f"[rag] ingest warn {e}")
        try:
            from resume.rag.manager import invalidate_manager
            invalidate_manager(uid)
        except Exception:
            pass
        merged = existing
        # build per-field diff
        per_field = []
        filled_fields = []
        still_needs = []
        all_keys = ["name","email","phone","highest_qualification","institution","total_experience_years","relevant_experience_years","current_location","skills"]
        for k in all_keys:
            before = before_for_diff.get("resume_facts",{}).get(k, "NEEDS_REVIEW")
            after = existing.get("resume_facts",{}).get(k, "NEEDS_REVIEW")
            filled = before in (None,"","NEEDS_REVIEW") and after not in (None,"","NEEDS_REVIEW")
            if filled: filled_fields.append(k)
            if after in (None,"","NEEDS_REVIEW"): still_needs.append(k)
            per_field.append({"field": f"resume_facts.{k}", "before": before, "after": after, "filled": filled})
        # detailed report keep-all
        import time, datetime, hashlib as _hl
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        ts_iso = datetime.datetime.now().isoformat()
        # get email for report
        try:
            from web.db import get_user_by_id
            uinfo = get_user_by_id(uid)
            email_full = uinfo.get("email") if uinfo else ""
        except: email_full = ""
        # redaction flag will be handled on read, store full
        report = {
            "uid": uid, "email": email_full, "ts": ts, "ts_iso": ts_iso,
            "upload": {"filename": file.filename, "ext": ext, "size_bytes": len(data), "mime": file.content_type or "", "client_size_ok": True},
            "saving": {"dest": str(dest), "md_path": str(md_path), "bytes_written": len(data), "md_chars": md_chars, "md_sha": md_sha, "saved_ok": True, "error": None, "atomic_tmp": True},
            "parsing": {"ext": ext, "raw_chars_initial": len(raw_initial) if ext==".pdf" else len(raw), "needs_ocr": needs_ocr_val, "needs_ocr_logic": "len<200 chars OR words<30 → fallback tesseract 300dpi", "ocr_attempted": ocr_attempted, "ocr_success": ocr_success, "ocr_error": ocr_error, "raw_chars_final": len(raw), "raw_snippet": raw[:500].replace("\n"," "), "normalize_ok": True},
            "extract": {"ocr_facts": ocr_facts, "facts_count": len(ocr_facts), "regex_version": "generic pytesseract v1 (no SSGI/IIT whitelist)"},
            "merge": {"before": before_for_diff, "after": existing, "per_field": per_field, "filled_fields": filled_fields, "still_needs_review": still_needs},
            "output": {"response_path": str(dest), "ocr_facts": ocr_facts, "merged": existing}
        }
        # save keep-all JSON + MD
        try:
            from web.per_user import get_user_reports_dir
            rep_dir = get_user_reports_dir(uid)
            rep_dir.mkdir(parents=True, exist_ok=True)
            rp_json = rep_dir / f"resume_parse_{ts}.json"
            tmpj = rp_json.with_suffix(".tmp")
            tmpj.write_text(json.dumps(report, indent=2))
            tmpj.replace(rp_json)
            # MD human readable
            md_lines = [f"# Resume Parse {ts}", f"- uid {uid} {email_full}", f"## Upload {file.filename} {len(data)}B {ext}", f"## Saving {md_chars} chars sha {md_sha}", f"## Parsing ext {ext} raw {len(raw)} needs_ocr {needs_ocr_val} ocr_success {ocr_success}", f"Snippet: {raw[:300]}", "## Extract", json.dumps(ocr_facts, indent=2), "## Merge per-field", json.dumps(per_field, indent=2)]
            (rep_dir / f"resume_parse_{ts}.md").write_text("\n".join(md_lines))
            # also DB
            try:
                from web.db import _conn
                conn = _conn()
                conn.execute("INSERT OR REPLACE INTO reports (user_id,kind,run_id,payload_json) VALUES (?,?,?,?)", (uid, "resume_parse", ts, json.dumps(report)))
                conn.commit(); conn.close()
            except: pass
        except Exception as e:
            print(f"[resume] report warn {e}")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[resume] ocr warn {e}")
        raise HTTPException(status_code=500, detail=f"Resume processing failed: {e}")
    try:
        from web.per_user import record_audit
        record_audit(uid, "resume_upload", {"filename": file.filename, "filled": locals().get("filled_fields", [])})
    except Exception:
        pass
    return {"ok": True, "path": str(dest), "ocr_facts": ocr_facts, "merged": merged, "report_id": locals().get("ts",""), "report_path": f"reports/{uid}/resume_parse_{locals().get('ts','')}.json", "parsing": {"raw_chars": len(raw), "needs_ocr": needs_ocr_val, "needs_ocr_logic": "len<200 chars OR words<30 → fallback tesseract 300dpi", "ocr_success": ocr_success, "raw_snippet": raw[:300] if 'raw' in locals() else ""}, "per_field": locals().get("per_field",[]), "filled_fields": locals().get("filled_fields",[]), "still_needs": locals().get("still_needs",[])}

@router.post("/naukri")
async def upload_naukri(request: Request, file: UploadFile = File(...), _=Depends(require_auth)):
    uid = request.session.get("user_id")
    if not uid: raise HTTPException(status_code=401, detail="Not authenticated")
    data = await file.read()
    if len(data) > 50*1024*1024:
        raise HTTPException(status_code=400, detail="ZIP too large")
    dest_dir = shard(uid) / "naukri_profile"
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest_dir / "tmp.zip"
    tmp.write_bytes(data)
    try:
        with zipfile.ZipFile(tmp) as z:
            z.extractall(dest_dir)
        tmp.unlink(missing_ok=True)
        # validate contains cookies.sqlite or not empty
        if not any(dest_dir.iterdir()):
            raise HTTPException(status_code=400, detail="Empty ZIP")
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP")
    try:
        from web.per_user import record_audit
        record_audit(uid, "naukri_upload", {"bytes": len(data)})
    except Exception:
        pass
    return {"ok": True}
