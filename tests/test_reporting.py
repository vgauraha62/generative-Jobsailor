from reporting import build_visit_summary, forms_items, JobResult

def _jr(status="applied", **kw):
    r = JobResult(status=status, job_type="p", url="https://u", path_taken="chat_widget")
    for k, v in kw.items():
        setattr(r, k, v)
    return r


def _ans(q="Q?", answer="A", provider="gemini", accepted=True, type="text"):
    return {"q_idx": 1, "type": type, "q": q, "options": None, "answer": answer,
            "provider": provider, "accepted": accepted, "timestamp": "t"}


def test_submit_entries_arent_form_answers():
    r = _jr(chat_transcript=[_ans(), {"q_idx": 2, "type": "submit", "q": None, "options": None,
                                      "answer": "Submit Application", "provider": "bot", "timestamp": "t"}])
    items = forms_items([r], "run1")
    assert len(items) == 1 and items[0]["type"] == "text"


def test_unaccepted_answers_dont_count():
    r = _jr(chat_transcript=[_ans(answer="Yes"), _ans(q="Q2?", answer="No", accepted=False),
                             {"q_idx": 3, "type": "submit", "q": None, "options": None,
                              "answer": "Save", "provider": "bot", "timestamp": "t"}])
    s = build_visit_summary([r])
    assert (s["answers_gemini"], s["answers_openrouter"], s["answers_cache"]) == (1, 0, 0)


def test_applied_verification_reported_separately():
    rs = [_jr(verified=v) for v in ("direct", "history", "revisit", "banner", None)]
    assert build_visit_summary(rs)["applied_verification"] == {
        "direct": 1, "banner": 1, "revisit": 1, "history": 1, "unmarked": 1}


def test_invalid_full_form_answers_dont_count():
    r = _jr(form_plan=[{"label": "A", "type": "text", "answer": "Pune", "provider": "gemini"},
                       {"label": "B", "type": "text", "answer": "", "provider": "gemini"},
                       {"label": "C", "type": "text", "answer": "NEEDS_REVIEW", "provider": "openrouter"}])
    s = build_visit_summary([r])
    assert (s["answers_gemini"], s["answers_openrouter"], s["answers_cache"]) == (1, 0, 0)

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
