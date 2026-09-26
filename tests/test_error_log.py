import json
import os
import time
from types import SimpleNamespace


def test_record_error_appends_failed(tmp_path, monkeypatch):
    import apply_jobs
    monkeypatch.setitem(apply_jobs.REPORTS_CFG, "dir", str(tmp_path))
    res = SimpleNamespace(status="failed", job_type="python-jobs", error_type="TimeoutException",
                          reason="nav failed", traceback="tb", path_taken="chat_widget")
    apply_jobs._record_error("http://a", res)
    apply_jobs._record_error("http://b", res)
    apply_jobs._record_error("http://c", SimpleNamespace(status="applied"))
    lines = (tmp_path / "errors.jsonl").read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["url"] == "http://a" and first["error_type"] == "TimeoutException" and first["at"]


def test_prune_logs(tmp_path):
    from web.routes_run import _prune_logs
    old = tmp_path / "run_20200101_000000.log"
    new = tmp_path / "run_20990101_000000.log"
    old.write_text("x")
    new.write_text("x")
    os.utime(old, (time.time() - 8 * 86400, time.time() - 8 * 86400))
    _prune_logs(tmp_path)
    assert not old.exists() and new.exists()
