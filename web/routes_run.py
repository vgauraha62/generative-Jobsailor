import json, re, os, signal, subprocess, time
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
import config_loader

router = APIRouter(prefix="/api/run")
RUN_LOCK = Path("reports/run.lock")
RUN_STATE = Path("reports/run_state.json")
_SLUG_RE = re.compile(r"^[a-z0-9\-]+$")
_proc = None
_logf = None

def _load_cfg():
    return config_loader.load_config()

def _per_user_lock(request: Request):
    try:
        uid = request.session.get("user_id")
        if uid:
            from web.per_user import get_user_reports_dir
            d = get_user_reports_dir(uid)
            return d / "run.lock", d / "run_state.json", d / f"run_{time.strftime('%Y%m%d_%H%M%S')}.log"
    except: pass
    return RUN_LOCK, RUN_STATE, Path(f"reports/run_{time.strftime('%Y%m%d_%H%M%S')}.log")

def _prune_logs(log_dir, days=7):
    # ponytail: prune run logs older than 7 days; keeps disk bounded, no rotation lib
    try:
        cutoff = time.time() - days * 86400
        for old in Path(log_dir).glob("run_*.log"):
            if old.stat().st_mtime < cutoff:
                old.unlink(missing_ok=True)
    except Exception:
        pass


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _is_bot(pid) -> bool:
    # ponytail: /proc cmdline guard vs pid reuse; non-Linux -> trust pid
    try:
        cmd = Path(f"/proc/{int(pid)}/cmdline").read_bytes().decode("utf-8", errors="replace")
        return "apply_jobs" in cmd
    except Exception:
        return True


def _resolve_locks(request: Request):
    # ponytail: status+stop+start share one resolution; prefer existing per-user lock, else global
    try:
        uid = request.session.get("user_id") if request else None
        if uid:
            from web.per_user import get_user_reports_dir
            d = get_user_reports_dir(uid)
            pu_lock, pu_state = d / "run.lock", d / "run_state.json"
            if pu_lock.exists():
                return pu_lock, pu_state
    except Exception:
        pass
    return RUN_LOCK, RUN_STATE


@router.get("/status")
async def run_status(request: Request = None):
    # per-user lock check first
    try:
        uid = request.session.get("user_id")
        if uid:
            from web.per_user import get_user_reports_dir
            d = get_user_reports_dir(uid)
            pu_lock = d / "run.lock"
            pu_state = d / "run_state.json"
            if pu_lock.exists():
                try:
                    data = json.loads(pu_lock.read_text())
                    log_tail = ""
                    try:
                        log_path = Path(data.get("log", ""))
                        if log_path.exists():
                            lines = log_path.read_text().splitlines()[-50:]
                            log_tail = "\n".join(lines)
                    except: pass
                    # ponytail: stale flagged only; explicit Stop click clears, never auto-unlink
                    pid = data.get("pid")
                    stale = not _alive(pid) if pid else True
                    if pid and stale is False and not _is_bot(pid):
                        stale = True
                    if stale:
                        log_tail = (log_tail + "\n" if log_tail else "") + f"(stale lock? pid {pid} dead or reused — press Stop to clear)"
                    return {"running": True, "lock": data, "log_tail": log_tail, "stale": stale}
                except: pass
            if pu_state.exists():
                try: return {"running": False, "last": json.loads(pu_state.read_text())}
                except: pass
    except: pass
    if RUN_LOCK.exists():
        try:
            data = json.loads(RUN_LOCK.read_text())
        except Exception:
            data = {"status": "running", "run_id": "unknown"}
        log_tail = ""
        try:
            log_path = Path(data.get("log", ""))
            if log_path.exists():
                lines = log_path.read_text().splitlines()[-50:]
                log_tail = "\n".join(lines)
        except Exception:
            pass
        # ponytail: stale flagged only; explicit Stop click clears, never auto-unlink
        pid = data.get("pid")
        stale = not _alive(pid) if pid else True
        if pid and stale is False and not _is_bot(pid):
            stale = True
        if stale:
            log_tail = (log_tail + "\n" if log_tail else "") + f"(stale lock? pid {pid} dead or reused — press Stop to clear)"
        return {"running": True, "lock": data, "log_tail": log_tail, "stale": stale}
    if RUN_STATE.exists():
        try:
            return {"running": False, "last": json.loads(RUN_STATE.read_text())}
        except Exception:
            pass
    return {"running": False}

@router.post("")
async def start_run(payload: dict, request: Request = None):
    cfg = _load_cfg()
    from dev_limits import gemini_limit_bypass_enabled
    dev_budget_bypass = gemini_limit_bypass_enabled()
    max_types = int(cfg.get("search", {}).get("max_run_types", 3))
    types = payload.get("types") or []
    raw_live = payload.get("live")
    if isinstance(raw_live, str):
        live = raw_live.lower() in ("true", "1", "yes", "on")
    else:
        live = bool(raw_live)
    print(f"[run] request live={live} raw={raw_live!r} types={types}")
    if live:
        try:
            import gemini_api as _ga
            hk = _ga.health_check(timeout=5) if hasattr(_ga, "health_check") else {"ok": True}
            if not hk.get("ok"):
                err = hk.get("error", "gemini health check failed")
                if "unauth" in err.lower() or "api key" in err.lower() or "permission" in err.lower():
                    raise HTTPException(status_code=400, detail=f"Gemini API key invalid: {err}")
                if ("quota" in err.lower() or "resource_exhausted" in err.lower() or "429" in err) and not dev_budget_bypass:
                    raise HTTPException(status_code=429, detail=f"Gemini quota exhausted: {err}")
        except HTTPException:
            raise
        except Exception as e:
            print(f"[run] health check warn: {e}")
    if not isinstance(types, list) or len(types)==0 or len(types)>max_types:
        raise HTTPException(status_code=400, detail=f"types must be 1-{max_types} items")
    norm = []
    for t in types:
        s = str(t).strip().lower()
        if not s:
            continue
        if not _SLUG_RE.match(s):
            raise HTTPException(status_code=400, detail=f"invalid type: {t}")
        if not s.endswith("-jobs"):
            s = s + "-jobs"
        norm.append(s)
    if not norm:
        raise HTTPException(status_code=400, detail="no valid types")
    if len(norm) > max_types:
        raise HTTPException(status_code=400, detail=f"max {max_types} types")
    # sentinel check for live (per-user)
    if live:
        uid_s = request.session.get("user_id") if request else None
        try:
            if uid_s:
                from web.per_user import get_user_profile_path
                pp = get_user_profile_path(uid_s)
                if pp.exists():
                    import json as _js
                    profile = json.loads(pp.read_text())
                else:
                    profile = {"resume_facts": {"name": "NEEDS_REVIEW", "email": "NEEDS_REVIEW", "phone": "NEEDS_REVIEW", "highest_qualification": "NEEDS_REVIEW", "institution": "NEEDS_REVIEW", "total_experience_years": "NEEDS_REVIEW", "relevant_experience_years": "NEEDS_REVIEW", "current_location": "NEEDS_REVIEW", "skills": "NEEDS_REVIEW"}, "user_preferences": {"current_ctc_lpa": "NEEDS_REVIEW", "expected_ctc_lpa": "NEEDS_REVIEW", "notice_period_days": "NEEDS_REVIEW", "willing_to_relocate": "NEEDS_REVIEW", "work_authorization": "NEEDS_REVIEW", "passport_valid": "NEEDS_REVIEW"}}
            else:
                import candidate_profile
                profile = candidate_profile.load_candidate_profile()
        except:
            profile = {"resume_facts": {"name": "NEEDS_REVIEW"}, "user_preferences": {"current_ctc_lpa": "NEEDS_REVIEW"}}
        import candidate_profile as _cp
        sents = _cp.find_sentinels(profile)
        if sents:
            raise HTTPException(status_code=400, detail=f"NEEDS_REVIEW: {', '.join(sents)}")
    # per-user lock
    uid = request.session.get("user_id") if request else None
    if uid:
        try:
            from web.per_user import get_user_reports_dir
            per_dir = get_user_reports_dir(uid)
            RUN_LOCK_U = per_dir / "run.lock"
            RUN_STATE_U = per_dir / "run_state.json"
            LOG_DIR_U = per_dir
        except:
            RUN_LOCK_U = RUN_LOCK
            RUN_STATE_U = RUN_STATE
            LOG_DIR_U = Path("reports")
    else:
        RUN_LOCK_U = RUN_LOCK
        RUN_STATE_U = RUN_STATE
        LOG_DIR_U = Path("reports")
    if RUN_LOCK_U.exists():
        raise HTTPException(status_code=409, detail="already running")
    run_id = time.strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR_U / f"run_{run_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _prune_logs(LOG_DIR_U)
    lock_data = {"status": "running", "run_id": run_id, "types": norm, "live": live, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "log": str(log_path), "user_id": uid}
    if RUN_LOCK_U.exists():
        raise HTTPException(status_code=409, detail="already running")
    try:
        RUN_LOCK_U.write_text(json.dumps(lock_data))
    except FileExistsError:
        raise HTTPException(status_code=409, detail="already running")
    cmd = ["venv/bin/python", "apply_jobs.py", "--types"] + [t.replace("-jobs","") for t in norm]
    if live:
        cmd.append("--live")
    # per-user env
    env = os.environ.copy()
    if uid:
        env["USER_ID"] = str(uid)
        try:
            from web.per_user import shard as _sh
            gem = _sh(uid) / ".env.gemini"
            if gem.exists():
                for line in gem.read_text().splitlines():
                    if line.startswith("GEMINI_API_KEY="):
                        env["GEMINI_API_KEY"] = line.split("=",1)[1].strip()
                    if line.startswith("GEMINI_MODEL=") and line.split("=",1)[1].strip():
                        env["GEMINI_MODEL"] = line.split("=",1)[1].strip()
        except: pass
    logf = open(log_path, "w")
    proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, cwd=str(Path.cwd()), start_new_session=True, env=env)
    lock_data["pid"] = proc.pid
    RUN_LOCK_U.write_text(json.dumps(lock_data))
    global _proc, _logf
    _proc = proc
    _logf = logf
    def _watch():
        import threading
        def w():
            proc.wait()
            try:
                logf.close()
            except Exception:
                pass
            try:
                RUN_LOCK_U.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                # fallback global for legacy
                if RUN_LOCK_U != RUN_LOCK:
                    RUN_LOCK.unlink(missing_ok=True)
            except: pass
            state = {"run_id": run_id, "types": norm, "live": live, "exit_code": proc.returncode, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "user_id": uid}
            if proc.returncode is not None and proc.returncode < 0:
                state["stopped"] = True
            try:
                RUN_STATE_U.write_text(json.dumps(state))
            except Exception:
                pass
            try:
                if RUN_STATE_U != RUN_STATE:
                    RUN_STATE.write_text(json.dumps(state))
            except: pass
            global _proc, _logf
            _proc = None
            _logf = None
        threading.Thread(target=w, daemon=True).start()
    _watch()
    try:
        from web.per_user import record_audit
        record_audit(uid, "run_start", {"run_id": run_id, "types": norm, "live": live})
    except Exception:
        pass
    return {"run_id": run_id, "types": norm, "live": live, "status": "running"}


@router.post("/stop")
async def stop_run(request: Request = None):
    LOCK, STATE = _resolve_locks(request)
    if not LOCK.exists():
        if STATE.exists():
            try:
                last = json.loads(STATE.read_text())
                if last.get("stopped"):
                    return {"stopped": True, "last": last}
            except Exception:
                pass
        raise HTTPException(status_code=404, detail="no running job")
    try:
        data = json.loads(LOCK.read_text())
    except Exception:
        data = {}
    run_id = data.get("run_id", "unknown")
    pid = data.get("pid")
    proc = globals().get("_proc")
    try:
        from web.per_user import record_audit
        _stop_uid = request.session.get("user_id") if request else None
        if _stop_uid:
            record_audit(_stop_uid, "run_stop", {"run_id": run_id})
    except Exception:
        pass
    if proc is not None and proc.poll() is None:
        pid = proc.pid
    if not pid:
        # ponytail: explicit click clears pid-less lock; status never auto-clears
        try:
            LOCK.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(status_code=404, detail="no running job (missing pid)")

    if pid and _alive(pid) and not _is_bot(pid) and (proc is None or proc.poll() is not None):
        # ponytail: pid reused by unrelated proc — clear lock, never kill strangers
        try:
            LOCK.unlink(missing_ok=True)
        except Exception:
            pass
        return {"stopped": True, "run_id": run_id, "detail": "stale lock cleared (pid reused)"}

    if not _alive(pid) and (proc is None or proc.poll() is not None):
        try:
            LOCK.unlink(missing_ok=True)
        except Exception:
            pass
        return {"stopped": True, "run_id": run_id, "detail": "already exited"}

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            if proc is not None and proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), sig)
                except Exception:
                    proc.send_signal(sig)
            else:
                try:
                    os.killpg(os.getpgid(pid), sig)
                except Exception:
                    os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            break
        except Exception:
            pass
        for _ in range(25):
            time.sleep(0.2)
            if proc is not None and proc.poll() is not None:
                return {"stopped": True, "run_id": run_id, "exit_code": proc.returncode}
            if not _alive(pid):
                return {"stopped": True, "run_id": run_id}
            if not LOCK.exists():
                return {"stopped": True, "run_id": run_id}
        if not _alive(pid) or (proc is not None and proc.poll() is not None):
            return {"stopped": True, "run_id": run_id}

    try:
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except Exception:
                os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    except Exception:
        pass
    for _ in range(15):
        time.sleep(0.2)
        if proc is not None and proc.poll() is not None:
            break
        if not _alive(pid):
            break
        if not LOCK.exists():
            break
    try:
        LOCK.unlink(missing_ok=True)
    except Exception:
        pass
    if proc is not None and proc.poll() is not None:
        state = {"run_id": run_id, "types": data.get("types", []), "live": data.get("live", False), "exit_code": proc.returncode, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "stopped": True}
        try:
            STATE.write_text(json.dumps(state))
        except Exception:
            pass
    return {"stopped": True, "run_id": run_id, "forced": True}
