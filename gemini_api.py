"""
Gemini AI integration for automating job application answers.

Uses the modern `google.genai` package and answers each job-application
question in isolation from the candidate's resume data, which is supplied
as the model's system instruction.
"""

import os

from dotenv import load_dotenv
from google import genai
from config_loader import load_config

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
# ponytail: OpenRouter optional; absent key = current Gemini behavior, nothing bricks
if not API_KEY and not os.getenv("OPENROUTER_API_KEY"):
    raise RuntimeError("GEMINI_API_KEY not set. Add it to the .env file.")

GEMINI_CFG = load_config()["gemini"]
MODEL_NAME = os.getenv("GEMINI_MODEL") or GEMINI_CFG["model"]

# Per-job Gemini call counter. Reset at the start of each process_job; the
# value is read back for visit-report attribution. Incremented in the same
# single funnel as the daily budget so the two can never disagree.
_job_calls = 0
_curation_calls = 0

# Last provider that produced an answer ("gemini" | "openrouter" | None).
# Read-only for callers stamping per-answer attribution; never drives routing.
last_provider = None


def reset_job_counter():
    global _job_calls
    _job_calls = 0


def job_count() -> int:
    return _job_calls


def reset_curation_counter():
    global _curation_calls
    _curation_calls = 0


def curation_count() -> int:
    return _curation_calls

def _build_system_instruction():
    try:
        from candidate_profile import load_candidate_profile
        profile = load_candidate_profile()
        # if profile is blank NEEDS_REVIEW, use generic
        import json as _js
        data = _js.dumps(profile, indent=2) if profile else ""
        # check if all NEEDS_REVIEW
        if "NEEDS_REVIEW" in data and len(profile.get("resume_facts",{}))>0:
            # build from actual profile, not hard-coded Vaibhav
            return (
                "You are an assistant that fills in a candidate's online job-application questions. "
                "Answer using ONLY the candidate data below. Be concise: minimum 1 word, average 2-3 words, maximum 5 words. "
                "If the question is a multi-choice question, respond with only the number (index) of the correct option.\n\n"
                f"CANDIDATE DATA\n{data}"
            )
        return (
            "You are an assistant that fills in a candidate's online job-application questions. "
            "Answer using ONLY the candidate data below. Be concise: minimum 1 word, average 2-3 words, maximum 5 words. "
            "If the question is a multi-choice question, respond with only the number (index) of the correct option.\n\n"
            f"CANDIDATE DATA\n{data}"
        )
    except:
        return (
            "You are an assistant that fills in a candidate's online job-application questions. "
            "Answer using ONLY the candidate data below. Be concise: minimum 1 word, average 2-3 words, maximum 5 words. "
            "If the question is a multi-choice question, respond with only the number (index) of the correct option."
        )

system_instruction = _build_system_instruction()

client = genai.Client(api_key=API_KEY) if API_KEY else None

last_health = {"ok": True, "last_checked": None, "error": None}


def _is_quota_error(e: Exception) -> bool:
    s = str(e).lower()
    # ponytail: retryable class (quota + transient); _classify splits spill vs halt
    return "429" in s or "resource_exhausted" in s or "quota" in s or "503" in s or "unavailable" in s or "overloaded" in s or "try again later" in s


def _is_auth_error(e: Exception) -> bool:
    s = str(e).lower()
    return "401" in s or "403" in s or "unauthenticated" in s or "permission_denied" in s or "api key" in s


class ModelOverloaded(Exception):
    """Persistent model overload after retries — the run should halt, not skip."""


def _classify(e: Exception) -> str:
    # ponytail: label once at failure; quota spills, overload halts, auth/other keep paths
    s = str(e).lower()
    if "429" in s or "quota" in s or "billing" in s or "exhausted" in s or "402" in s or "resource_exhausted" in s:
        return "quota"
    if "503" in s or "unavailable" in s or "overloaded" in s or "try again later" in s or "500" in s or "502" in s or "504" in s:
        return "overload"
    return "other"


def _spillover(question, preset="micro") -> str | None:
    """One OpenRouter try on quota exhaustion. Returns text or None. Never raises."""
    # ponytail: spill one way, once; quota spends key, spike never does
    global last_provider
    try:
        model = openrouter_model(preset if preset in _OR_CAPS else "micro")
        key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
        if not model or not key:
            print("[gemini_api] quota spill unavailable (no OpenRouter key/model)")
            return None
        out = openrouter_complete(model, _build_system_instruction(), question, preset=preset if preset in _OR_CAPS else "micro")
        print("[gemini_api] quota spillover → openrouter ok")
        last_provider = "openrouter"
        return out or None
    except Exception as e:
        print(f"[gemini_api] spillover failed: {e}")
        return None


def openrouter_spend() -> dict | None:
    """Key spend meter: {usage, limit, pct} or None when unconfigured/unreachable. Never raises."""
    # ponytail: meter is advisory; callers halt only on confirmed numbers, never on probe failure
    try:
        import json as _js
        import urllib.request as _url
        key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
        if not key:
            return None
        req = _url.Request("https://openrouter.ai/api/v1/auth/key", headers={"Authorization": "Bearer " + key})
        with _url.urlopen(req, timeout=15) as r:
            d = (_js.loads(r.read().decode("utf-8", errors="replace")) or {}).get("data", {})
        usage = float(d.get("usage") or 0)
        limit = float(d.get("limit") or 0)
        if limit <= 0:
            return None
        return {"usage": usage, "limit": limit, "pct": usage / limit}
    except Exception as e:
        print(f"[gemini_api] spend probe warn: {e}")
        return None


def _retry_delay(e: Exception) -> float:
    import re
    m = re.search(r"retry[^0-9]*([0-9]+(?:\.[0-9]+)?)s", str(e).lower())
    if m:
        try:
            return min(float(m.group(1)), 30)
        except Exception:
            pass
    return 2.0


def health_check(timeout=5) -> dict:
    import time as _t
    from datetime import datetime
    try:
        result = {}

        def _w():
            try:
                result["text"] = _generate("ping")
            except Exception as ex:
                result["error"] = ex

        import threading
        th = threading.Thread(target=_w, daemon=True)
        th.start()
        th.join(timeout)
        if th.is_alive():
            last_health.update({"ok": False, "last_checked": datetime.now().isoformat(), "error": "timeout"})
            return {"ok": False, "error": "timeout", "model": MODEL_NAME}
        if "error" in result:
            e = result["error"]
            err_s = str(e)[:300]
            if _is_auth_error(e):
                last_health.update({"ok": False, "last_checked": datetime.now().isoformat(), "error": err_s})
                return {"ok": False, "error": err_s, "model": MODEL_NAME}
            if _is_quota_error(e):
                last_health.update({"ok": False, "last_checked": datetime.now().isoformat(), "error": err_s})
                return {"ok": False, "error": err_s, "model": MODEL_NAME}
            last_health.update({"ok": False, "last_checked": datetime.now().isoformat(), "error": err_s})
            return {"ok": False, "error": err_s, "model": MODEL_NAME}
        last_health.update({"ok": True, "last_checked": datetime.now().isoformat(), "error": None})
        return {"ok": True, "model": MODEL_NAME}
    except Exception as e:
        last_health.update({"ok": False, "last_checked": datetime.now().isoformat(), "error": str(e)[:300]})
        return {"ok": False, "error": str(e)[:300], "model": MODEL_NAME}


def _openrouter_cfg() -> dict:
    try:
        from config_loader import load_config as _lc
        return (_lc() or {}).get("openrouter", {}) or {}
    except Exception:
        return {}


def openrouter_model(kind: str = "micro") -> str | None:
    oc = _openrouter_cfg()
    return (os.environ.get("OPENROUTER_MODEL") or oc.get(kind) or oc.get("micro") or "").strip() or None


# ponytail: per-preset caps fit 4K-credit keys; clamped, never fatal
_OR_CAPS = {"micro": 50, "form": 500, "reviewer": 500, "proposer": 2500}

# ponytail: caps sized to the answer shape (digit/words vs 12-field JSON); config 1000 stays ceiling
_GEMINI_CAPS = {"micro": 50, "form": 500}


def openrouter_complete(model: str, system: str, user: str, timeout: int = 40, max_tokens: int | None = None, preset: str = "micro") -> str:
    """POST OpenRouter /chat/completions via stdlib. Returns stripped text or raises."""
    import json as _js
    import urllib.request as _url
    import urllib.error as _urlerr
    key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    oc = _openrouter_cfg()
    try:
        want = int(oc.get("max_tokens_" + preset, _OR_CAPS.get(preset, 1000)) if max_tokens is None else max_tokens)
    except (TypeError, ValueError):
        want = 1000
    want = max(1, min(want, 4000))  # ponytail: clamp to 4K afford; 402-proof the request line
    base = (oc.get("base_url") or "https://openrouter.ai/api/v1").rstrip("/")
    body = _js.dumps({"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "max_tokens": want}).encode()
    req = _url.Request(base + "/chat/completions", data=body, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with _url.urlopen(req, timeout=timeout) as r:
            data = _js.loads(r.read().decode("utf-8", errors="replace"))
    except _urlerr.HTTPError as e:
        if e.code == 402:
            raise RuntimeError("openrouter_402: key affords < requested; lower max_tokens or add credits") from e
        raise
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"OpenRouter bad response: {str(data)[:200]}") from e


def _own_gemini_key(uid=None) -> bool:
    try:
        uid = uid or os.environ.get("USER_ID")
        if not uid:
            return False
        from web.per_user import shard as _sh
        gem = _sh(int(uid)) / ".env.gemini"
        if not gem.exists():
            return False
        return any(l.startswith("GEMINI_API_KEY=") and l.split("=", 1)[1].strip() for l in gem.read_text().splitlines())
    except Exception:
        return False


def provider_for(uid=None) -> str:
    # ponytail: shard file is truth (env mixes operator+user sources); operator key never leaves process env
    # ponytail: Gemini key present = Gemini primary, OpenRouter is spill-only; pool-primary only with no Gemini key at all
    if _own_gemini_key(uid):
        return "gemini_own"
    if (os.getenv("GEMINI_API_KEY") or "").strip():
        return "gemini_global"
    if (os.getenv("OPENROUTER_API_KEY") or "").strip() and openrouter_model("micro"):
        return "openrouter"
    return "gemini_global"


def _generate(question, max_tokens=None):
    """LLM single-shot; provider picked by key ownership, never mixed."""
    global last_provider
    if provider_for() == "openrouter":
        out = openrouter_complete(openrouter_model("micro"), _build_system_instruction(), question, max_tokens=max_tokens)
        last_provider = "openrouter"
        return out
    if client is None:
        raise RuntimeError("GEMINI_API_KEY not set. Add it to the .env file.")
    config = genai.types.GenerateContentConfig(
        system_instruction=_build_system_instruction(),
        temperature=GEMINI_CFG["temperature"],
        top_p=GEMINI_CFG["top_p"],
        top_k=GEMINI_CFG["top_k"],
        max_output_tokens=max_tokens or GEMINI_CFG["max_output_tokens"],
    )
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=question,
        config=config,
    )
    last_provider = "gemini"
    return (response.text or "").strip()


def _get_user_tz():
    try:
        import os as _os
        uid = _os.environ.get("USER_ID")
        if uid:
            from web.db import get_user_by_id as _g
            u = _g(int(uid))
            if u and u.get("timezone"):
                return u["timezone"]
    except Exception:
        pass
    return None

def bard_flash_response_curation(question, timeout=None) -> str:
    from config_loader import load_config as _lc
    global _curation_calls
    tz = _get_user_tz()
    try:
        import os as _os
        uid = int(_os.environ.get("USER_ID")) if _os.environ.get("USER_ID") else None
        if uid:
            from web.per_user import load_user_budget as _lub, curation_budget_ok as _cbok
            from web.per_user import record_user_budget_call as _rec
            try:
                from web.per_user import load_user_budget
                b = load_user_budget(uid, "curation", tz)
            except Exception:
                from state import load_curation_budget as _lcb
                b = _lcb(tz)
            lim = _lc().get("resume_curation", {}).get("gemini_daily_limit", 50)
            try:
                from web.per_user import load_user_budget as _lb2
                if not _lb2 or True:
                    pass
            except: pass
            if b.get("calls_used", 0) >= lim:
                print("[curation] budget exhausted, skipping Gemini call")
                return ""
            _curation_calls += 1
            try:
                from web.per_user import record_user_budget_call as _r
                _r(uid, "curation", tz)
            except Exception:
                from state import load_curation_budget as _lcb2, record_curation_call as _rcc
                _rcc(_lcb2(tz))
        else:
            from state import load_curation_budget, record_curation_call, curation_budget_ok
            b = load_curation_budget(tz)
            lim = _lc().get("resume_curation", {}).get("gemini_daily_limit", 50)
            if not curation_budget_ok(b, lim):
                print("[curation] budget exhausted, skipping Gemini call")
                return ""
            _curation_calls += 1
            record_curation_call(load_curation_budget(tz))
    except Exception:
        from state import load_curation_budget as _lcb_f, record_curation_call as _rcc_f, curation_budget_ok as _cbok_f
        b = _lcb_f(tz)
        lim = _lc().get("resume_curation", {}).get("gemini_daily_limit", 50)
        if not _cbok_f(b, lim):
            print("[curation] budget exhausted, skipping Gemini call")
            return ""
        _curation_calls += 1
        _rcc_f(_lcb_f(tz))

    def _call_once(to):
        if not to:
            try:
                return _generate(question), None
            except Exception as ex:
                return None, ex
        res = {}

        def _worker():
            try:
                res["text"] = _generate(question)
            except Exception as ex:
                res["error"] = ex

        import threading
        th = threading.Thread(target=_worker, daemon=True)
        th.start()
        th.join(to)
        if th.is_alive():
            return None, TimeoutError("timeout")
        if "error" in res:
            return None, res["error"]
        return res.get("text", ""), None

    txt, err = _call_once(timeout)
    if err is not None:
        if _classify(err) == "quota":
            spilled = _spillover(question, "form")  # ponytail: keyword arrays need room; micro would truncate
            if spilled:
                return spilled
            print(f"[curation] quota exhausted ({err}); no spill target.")
            return ""
        if _is_quota_error(err):
            print(f"[curation] overload, retry once then skip: {err}")
            import time
            time.sleep(_retry_delay(err))
            txt2, err2 = _call_once(timeout)
            if err2 is None:
                return txt2 or ""
            print(f"[curation] retry failed: {err2}")
            return ""
        if _is_auth_error(err):
            print(f"[curation] auth error (no retry): {err}")
            return ""
        print(f"[curation] error: {err}")
        return ""
    return txt or ""


def bard_flash_response(question, timeout=None, preset="micro") -> str:
    """Answer a single application question from the resume data.

    Makes an isolated generate request per call so answers do not get
    polluted by questions from earlier jobs. `timeout` (seconds) is optional;
    when set, the call is bounded by a watchdog thread so a slow response
    returns "" instead of blocking the driver across a staleness window.
    `preset` sizes output tokens to the answer shape ("micro" Q&A vs "form" JSON).

    Records one call against the daily Gemini budget up front, so both the
    direct and watchdog-threaded code paths count exactly once per
    invocation (success or failure).
    """
    global _job_calls
    _job_calls += 1
    cap = _GEMINI_CAPS.get(preset, 50)
    try:
        import os as _os2
        uid2 = int(_os2.environ.get("USER_ID")) if _os2.environ.get("USER_ID") else None
        tz2 = _get_user_tz()
        if uid2:
            from web.per_user import record_user_budget_call as _r2
            _r2(uid2, "gemini", tz2)
        else:
            from state import load_budget as _lb_g, record_gemini_call as _rgc
            _rgc(_lb_g(tz2))
    except Exception:
        from state import load_budget as _lb_f, record_gemini_call as _rgc_f
        _rgc_f(_lb_f(_get_user_tz()))

    def _call_once(to):
        if not to:
            try:
                return _generate(question, cap), None
            except Exception as ex:
                return None, ex
        res = {}

        def _worker():
            try:
                res["text"] = _generate(question, cap)
            except Exception as ex:
                res["error"] = ex

        import threading
        th = threading.Thread(target=_worker, daemon=True)
        th.start()
        th.join(to)
        if th.is_alive():
            return None, TimeoutError("timeout")
        if "error" in res:
            return None, res["error"]
        return res.get("text", ""), None

    txt, err = _call_once(timeout)
    if err is not None:
        if _classify(err) == "quota":
            spilled = _spillover(question, preset)
            if spilled:
                return spilled
            print(f"[gemini_api] quota exhausted ({err}); no spill target.")
            return ""
        if _is_quota_error(err):
            # ponytail: 2 local retries, then halt the run — silent skips hide real outages
            for _ in range(2):
                delay = _retry_delay(err)
                if delay > 3:
                    break
                import time
                time.sleep(delay)
                txt2, err2 = _call_once(timeout)
                if err2 is None:
                    return txt2 or ""
                err = err2
                if _classify(err) == "quota":
                    spilled = _spillover(question, preset)
                    if spilled:
                        return spilled
                    print(f"[gemini_api] quota exhausted ({err}); no spill target.")
                    return ""
            raise ModelOverloaded(f"model overloaded after retries: {err}")
        if _is_auth_error(err):
            print(f"An error occurred: auth error (no retry): {err}")
            return ""
        print(f"An error occurred: {err}")
        return ""
    return txt or ""


def generate_rag_response(prompt: str, system_instruction: str = None, max_tokens: int = 1200, temperature: float = 0.2, timeout: int = 8) -> str:
    """Generate rich RAG synthesis or JD match analysis without concise form-filling constraints."""
    res_holder = {}

    def _worker():
        try:
            config = genai.types.GenerateContentConfig(
                system_instruction=system_instruction or "You are an objective, expert career assistant. Output clear, well-structured GitHub markdown.",
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
            res = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=config,
            )
            res_holder["text"] = (res.text or "").strip()
        except Exception as e:
            res_holder["error"] = e

    import threading
    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    th.join(timeout)

    if th.is_alive():
        print(f"[rag_gemini] call timed out after {timeout}s")
        return ""

    if "error" in res_holder:
        print(f"[rag_gemini] error: {res_holder['error']}")
        return ""

    return res_holder.get("text", "")