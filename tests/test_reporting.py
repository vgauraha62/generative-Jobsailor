from reporting import build_visit_summary, JobResult

def test_summary_curation():
    rs=[JobResult(status="applied", curation_score=0.9, curation_performed=True, upload_status="uploaded", curation_calls_this_job=2),
        JobResult(status="failed", curation_score=0.3, curation_performed=True, upload_status="upload_failed"),
        JobResult(status="applied", curation_score=0.8, curation_performed=False, upload_status="skipped_high_score")]
    s=build_visit_summary(rs)
    assert s["curation_performed"]==2
    assert s["by_upload_status"]["uploaded"]==1
    assert s["avg_curation_score"]>0.6
    assert "0.8-1.0" in s["curation_score_histogram"]

def test_summary_empty():
    s=build_visit_summary([])
    assert s["avg_curation_score"]==0.0
