"""Deep e2e probe — every function with error report.

Mocks Gemini + Driver where needed, exercises real file I/O + PDF + scoring.

Usage:
  venv/bin/python scripts/run_curation_e2e.py
  venv/bin/python scripts/run_curation_e2e.py --live  # hits real Naukri (needs profile + network)

Writes: reports/e2e_<ts>.json + curated pdf
"""
import os, sys, json, time, traceback
from datetime import datetime
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def step(name, fn):
    t0=time.monotonic()
    try:
        out=fn()
        return {"step":name,"status":"ok","duration":round(time.monotonic()-t0,2),"output":str(out)[:300]}
    except Exception as e:
        return {"step":name,"status":"failed","error":type(e).__name__,"reason":str(e)[:400],"traceback":traceback.format_exc()[:2000],"duration":round(time.monotonic()-t0,2)}

def main():
    live="--live" in sys.argv
    results=[]
    results.append(step("ingest", lambda: __import__("resume.ingest", fromlist=["ingest"]).ingest("resume/vaibhav_gauraha_7987458402.pdf")))
    base_md=open("resumes/base.md",encoding="utf-8").read() if os.path.exists("resumes/base.md") else ""
    results.append(step("load_base_md", lambda: f"{len(base_md)} chars"))

    # scorer with mocked gemini (deep) + real fallback probe
    def do_score():
        import gemini_api, resume.scorer as sc
        orig=sc.bard_flash_response_curation if hasattr(sc,"bard_flash_response_curation") else None
        # mock to avoid real call unless live
        if not live:
            import unittest.mock as mock
            with mock.patch("gemini_api.bard_flash_response_curation", lambda q,t=None: '["python","rag","docker","kubernetes"]'):
                return sc.score_jd_vs_resume("Need Python RAG Docker", base_md)
        else:
            return sc.score_jd_vs_resume("Need Python RAG Docker", base_md)
    results.append(step("scorer", do_score))

    def do_curate():
        import gemini_api, resume.curator as cu
        if not live:
            import unittest.mock as mock
            with mock.patch("gemini_api.bard_flash_response_curation", lambda q,t=None: base_md+"\n\n## Curated for RAG"):
                c=cu.curate_md(base_md, "JD python rag")
                p,h=cu.save_curated(c, "JD python rag")
                return f"{p} {h} {len(c)}"
        else:
            import resume.curator as cu
            c=cu.curate_md(base_md, "JD python rag")
            p,h=cu.save_curated(c, "JD python rag")
            return f"{p} {h}"
    results.append(step("curator+save", do_curate))

    results.append(step("builder", lambda: __import__("resume.builder", fromlist=["md_to_pdf"]).md_to_pdf("resumes/base.md", "reports/e2e_test.pdf") or "pdf ok"))

    def do_gate():
        from resume.jd import has_surface, extract_jd
        class FakeD:
            def find_elements(self,a,b): return []
            def find_element(self,a,b): raise Exception()
            @property
            def page_source(self): return ""
        assert has_surface(FakeD())=="none"
        return "gate ok"
    results.append(step("gate_probe", do_gate))

    def do_uploader_mock():
        from resume.uploader import upload_to_naukri
        class FakeD:
            def get(self,u): pass
            def find_elements(self,*a,**k): return []
            def find_element(self,*a,**k): raise Exception("no")
            @property
            def page_source(self): return ""
        ok=upload_to_naukri(FakeD(), "reports/e2e_test.pdf", timeout=1)
        return f"upload mock -> {ok} (expect False)"
    results.append(step("uploader_mock", do_uploader_mock))

    if live:
        results.append(step("live_apply_1job", lambda: __import__("subprocess").check_output(["venv/bin/python","apply_jobs.py","--types","python"], text=True, timeout=120)[:500]))

    ts=datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path=f"reports/e2e_{ts}.json"
    payload={"ts":ts,"live":live,"steps":results,"summary":{"ok":sum(1 for r in results if r["status"]=="ok"),"failed":sum(1 for r in results if r["status"]=="failed")}}
    os.makedirs("reports", exist_ok=True)
    with open(out_path,"w") as f: json.dump(payload,f,indent=2)
    print(json.dumps(payload,indent=2))
    print(f"\n[e2e] written {out_path}  ok {payload['summary']['ok']}/{len(results)}")
    sys.exit(1 if payload["summary"]["failed"]>0 else 0)

if __name__=="__main__": main()
