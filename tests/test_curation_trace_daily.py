import json
import asyncio
from pathlib import Path
from unittest.mock import patch


def _make_visit(tmp, run_id, day, changed, uploaded):
    data = {
        "run_id": run_id,
        "started_at": f"{day}T10:00:00",
        "budget_at_end": {"day": day, "calls_used": 5},
        "curation_budget_at_end": {"day": day, "calls_used": 2},
        "summary": {
            "curation_performed": changed,
            "by_upload_status": {"uploaded": uploaded},
            "by_status": {"applied": 1},
        },
    }
    p = Path(tmp) / f"visit_{run_id}.json"
    with open(p, "w") as f:
        json.dump(data, f)
    return p


def test_curation_trace_resets_daily(tmp_path):
    import state
    import config_loader
    import web.routes_status as rs

    today = "2026-08-28"
    yday = "2026-08-27"

    _make_visit(tmp_path, "20260828_101010", today, 1, 1)
    _make_visit(tmp_path, "20260828_111111", today, 2, 0)
    _make_visit(tmp_path, "20260827_101010", yday, 10, 10)

    fake_cfg = {
        "reports": {"dir": str(tmp_path)},
        "gemini": {"daily_call_limit": 19},
        "resume_curation": {"gemini_daily_limit": 50, "match_threshold": 0.5, "active_resume": "resumes/active.json"},
        "apply": {"dry_run": True},
    }

    with patch.object(state, "load_visited", return_value={}), \
         patch.object(state, "load_budget", return_value={"day": today, "calls_used": 5}), \
         patch.object(state, "load_curation_budget", return_value={"day": today, "calls_used": 3}), \
         patch("candidate_profile.load_candidate_profile", return_value={}), \
         patch("candidate_profile.find_sentinels", return_value=[]), \
         patch.object(config_loader, "load_config", return_value=fake_cfg):

        result = asyncio.run(rs.get_status())
        ct = result["curation_trace"]
        assert ct["changed_total"] == 3, ct
        assert ct["uploaded_total"] == 1, ct
        assert ct["runs_with_curation"] == 2, ct
        assert ct["day"] == today


def test_curation_trace_empty_when_no_today(tmp_path):
    import state
    import config_loader
    import web.routes_status as rs

    today = "2026-08-29"
    _make_visit(tmp_path, "20260828_101010", "2026-08-28", 5, 5)

    fake_cfg = {
        "reports": {"dir": str(tmp_path)},
        "gemini": {"daily_call_limit": 19},
        "resume_curation": {"gemini_daily_limit": 50, "match_threshold": 0.5, "active_resume": "resumes/active.json"},
        "apply": {"dry_run": True},
    }

    with patch.object(state, "load_visited", return_value={}), \
         patch.object(state, "load_budget", return_value={"day": today, "calls_used": 0}), \
         patch.object(state, "load_curation_budget", return_value={"day": today, "calls_used": 0}), \
         patch("candidate_profile.load_candidate_profile", return_value={}), \
         patch("candidate_profile.find_sentinels", return_value=[]), \
         patch.object(config_loader, "load_config", return_value=fake_cfg):

        result = asyncio.run(rs.get_status())
        ct = result["curation_trace"]
        assert ct["changed_total"] == 0
        assert ct["uploaded_total"] == 0
        assert ct["runs_with_curation"] == 0


def test_curation_trace_fallback_to_run_id(tmp_path):
    import state
    import config_loader
    import web.routes_status as rs

    today = "2026-08-28"
    data = {
        "run_id": "20260828_121212",
        "summary": {"curation_performed": 1, "by_upload_status": {"uploaded": 1}, "by_status": {}},
    }
    p = Path(tmp_path) / "visit_20260828_121212.json"
    with open(p, "w") as f:
        json.dump(data, f)

    data2 = {
        "run_id": "20260827_121212",
        "summary": {"curation_performed": 9, "by_upload_status": {"uploaded": 9}, "by_status": {}},
    }
    p2 = Path(tmp_path) / "visit_20260827_121212.json"
    with open(p2, "w") as f:
        json.dump(data2, f)

    fake_cfg = {
        "reports": {"dir": str(tmp_path)},
        "gemini": {"daily_call_limit": 19},
        "resume_curation": {"gemini_daily_limit": 50, "match_threshold": 0.5, "active_resume": "resumes/active.json"},
        "apply": {"dry_run": True},
    }

    with patch.object(state, "load_visited", return_value={}), \
         patch.object(state, "load_budget", return_value={"day": today, "calls_used": 0}), \
         patch.object(state, "load_curation_budget", return_value={"day": today, "calls_used": 0}), \
         patch("candidate_profile.load_candidate_profile", return_value={}), \
         patch("candidate_profile.find_sentinels", return_value=[]), \
         patch.object(config_loader, "load_config", return_value=fake_cfg):

        result = asyncio.run(rs.get_status())
        ct = result["curation_trace"]
        assert ct["changed_total"] == 1
        assert ct["runs_with_curation"] == 1
