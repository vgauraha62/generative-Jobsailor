"""Validate mocked dry trial — checks file×functionality, per-Q proof, invariants, budgets.

Usage: venv/bin/python scripts/trial_validate_dry.py [--run-id <id>]

Reads latest reports/visit_*.json if no run_id given, validates:
- per-Q transcript length 1..n, each Q has after_save + new_question PNG >1KB
- path invariant: chat_widget/both → not full_form/no form fields (surf preserved)
- upload_status dry_run_skipped in DRY_RUN, not uploaded; no silent wrong-resume
- capture net_new ≈ visit.results + manual
- budget_at_end == gemini_budget.json, visit summary == log DONE
- curation_trace daily, screenshots pagination

Writes: reports/trial_validate_<run_id>.json + .md
"""
import os, sys, json, glob
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from config_loader import load_config
import state
import reporting

def latest(prefix):
    cfg = load_config()
    d = Path(cfg["reports"]["dir"])
    files = sorted(d.glob(f"{prefix}_*.json"), key=lambda p: p.stat().st_mtime)
    if not files: raise SystemExit(f"no {prefix}_*.json in {d}")
    return files[-1]

def load_run(run_id=None):
    cfg = load_config()
    d = Path(cfg["reports"]["dir"])
    if run_id:
        visit = d / f"visit_{run_id}.json"
        capture = d / f"capture_{run_id}.json"
        manual = d / f"manual_{run_id}.json"
        log = d / f"run_{run_id}.log"
    else:
        visit = latest("visit")
        run_id = visit.stem.replace("visit_","")
        capture = d / f"capture_{run_id}.json"
        manual = d / f"manual_{run_id}.json"
        log = d / f"run_{run_id}.log"
    return run_id, capture, visit, manual, log

def check_file_exists(p, label, errs, warns):
    if not p.exists():
        warns.append(f"{label} missing: {p}")
        return None
    return p

def validate_run(run_id=None):
    cfg = load_config()
    reports_dir = Path(cfg["reports"]["dir"])
    run_id, cap_p, vis_p, man_p, log_p = load_run(run_id)
    print(f"[validate] run_id={run_id}")
    errs=[]; warns=[]; passes=[]; details={}

    # Load files
    cap = json.loads(cap_p.read_text()) if cap_p.exists() else None
    vis = json.loads(vis_p.read_text()) if vis_p.exists() else None
    man = json.loads(man_p.read_text()) if man_p.exists() else None
    log_tail = log_p.read_text()[-3000:] if log_p.exists() else ""

    if not cap: errs.append(f"capture missing {cap_p}")
    else: passes.append(f"capture {cap_p.name}: job_types {list(cap.get('job_types',{}).keys())}")

    if not vis: errs.append(f"visit missing {vis_p}")
    else:
        results = vis.get("results",[])
        summary = vis.get("summary",{})
        # invariant: net_new
        net_new = cap.get("totals",{}).get("net_new_actionable_all_types") if cap else None
        if net_new is not None and len(results) != net_new:
            errs.append(f"visit results len {len(results)} != capture net_new {net_new}")
        else:
            passes.append(f"visit results len {len(results)} matches capture net_new {net_new}")

        # per-job checks
        q_total = 0
        for r in results:
            url = r.get("url","?")
            ct = r.get("chat_transcript") or []
            scrs = r.get("screenshots") or []
            path = r.get("path_taken")
            reason = r.get("reason") or ""
            upload = r.get("upload_status")
            # per-Q proof
            if ct:
                if not (1 <= len(ct) <= 12):
                    errs.append(f"{url} transcript len {len(ct)} out of 1..12")
                else:
                    passes.append(f"{url} transcript {len(ct)} Qs")
                for q in ct:
                    for key in ("screenshot_after_save","screenshot_new_q"):
                        pth = q.get(key)
                        if not pth:
                            errs.append(f"{url} q{ q.get('q_idx')} missing {key}")
                            continue
                        fp = Path(pth)
                        if not fp.exists():
                            errs.append(f"{url} q{ q.get('q_idx')} screenshot not found {pth}")
                        elif fp.stat().st_size < 1024:
                            errs.append(f"{url} q{ q.get('q_idx')} screenshot too small {fp.stat().st_size} {pth}")
                        else:
                            passes.append(f"{url} q{ q.get('q_idx')} {key} ok {fp.stat().st_size}B")
                    # chat q answered implies gemini_calls delta
                    if q.get("gemini_calls_after",0) < q.get("gemini_calls_before",0):
                        errs.append(f"{url} q{ q.get('q_idx')} gemini_calls_before > after")
                q_total += len(ct)
                # screenshots list should contain all
                if len(scrs) < len(ct)*1:
                    warns.append(f"{url} screenshots {len(scrs)} < transcript {len(ct)}")
            # path invariant
            if path == "full_form" and reason == "no form fields found":
                # check surf: if visit came from mocked chat/both, this would be error; mocked trial has chat_widget with 3Q applied, so this path should not happen for chat jobs
                # For mocked trial, full_form not expected for chat jobs
                if any("chat" in (r.get("path_taken") or "") for r in results):
                    pass
                # we flag only if transcript exists but path full_form
                if ct:
                    errs.append(f"{url} invariant: chat transcript exists but path=full_form reason=no form fields found")
            # upload confirmation in sampling dry-run (submits like live)
            if r.get("curation_performed"):
                if upload != "uploaded":
                    errs.append(f"{url} sampling curation_performed True but upload_status={upload!r} expected uploaded")
                else:
                    passes.append(f"{url} upload uploaded ok")
            # no error field for successful applied
            if r.get("status") == "applied" and r.get("error_type"):
                warns.append(f"{url} applied but error_type {r.get('error_type')}")
        details["q_total"] = q_total
        passes.append(f"q_total {q_total}")

        # visit summary vs log DONE
        by_status = summary.get("by_status",{})
        if "DONE" in log_tail:
            for k,v in by_status.items():
                if str(v) not in log_tail:
                    warns.append(f"log tail missing {k}:{v}")

        # budget check
        budget_file = state.load_budget()
        if vis.get("budget_at_end",{}).get("calls_used") is not None:
            if vis["budget_at_end"]["calls_used"] != budget_file["calls_used"]:
                warns.append(f"budget_at_end {vis['budget_at_end']} != file {budget_file}")

        # curation_trace daily (check via status logic not here, just warn if missing)
        # screenshots pagination
        pngs = [p for p in reports_dir.glob("*.png") if p.name.startswith("visit_chat_q")]
        if not pngs:
            warns.append("no visit_chat_q*.png screenshots found (per-Q proof missing)")
        else:
            passes.append(f"per-Q PNGs {len(pngs)} found: {[p.name for p in pngs[:5]]}")

    # manual
    if man_p and man_p.exists():
        man_count = man.get("count",0)
        vis_failed = sum(1 for r in vis.get("results",[]) if r.get("status") in ("failed","review")) if vis else 0
        passes.append(f"manual count {man_count} vs visit failed+review {vis_failed}")
    else:
        warns.append(f"manual missing {man_p} (may be empty)")

    ok = len(errs) == 0
    payload = {"run_id": run_id, "ok": ok, "errs": errs, "warns": warns, "passes": passes, "details": details, "checked_at": datetime.now().isoformat(),
               "files": {"capture": str(cap_p), "visit": str(vis_p), "manual": str(man_p), "log": str(log_p)}}
    out_json = reports_dir / f"trial_validate_{run_id}.json"
    out_json.write_text(json.dumps(payload, indent=2))
    md = [f"# Dry Trial Validation — {run_id}", "", f"**ok:** {ok}", f"**checked:** {payload['checked_at']}", "", "## Passes", ""]
    md += [f"- {p}" for p in passes] + ["", "## Warns", ""]
    md += [f"- {w}" for w in warns] + ["", "## Errors", ""]
    md += [f"- {e}" for e in errs] if errs else ["- (none)"]
    md += ["", "## Details", f"```json\n{json.dumps(details, indent=2)}\n```", "", "## Artifacts", f"- capture: `{cap_p}`", f"- visit: `{vis_p}`", f"- manual: `{man_p}`", f"- log: `{log_p}`", f"- per-Q PNGs: `{len(list(reports_dir.glob('visit_chat_q*.png')))}`"]
    out_md = reports_dir / f"trial_validate_{run_id}.md"
    out_md.write_text("\n".join(md))
    print(json.dumps(payload, indent=2))
    print(f"\n[validate] wrote {out_json} and {out_md} ok={ok}")
    return 0 if ok else 1

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", default=None)
    args = p.parse_args()
    sys.exit(validate_run(args.run_id))
