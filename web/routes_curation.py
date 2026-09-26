import json
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
import config_loader

router = APIRouter(prefix="/api/curation")


@router.patch("/threshold")
async def set_threshold(payload: dict):
    val = payload.get("threshold")
    if val is None:
        raise HTTPException(status_code=400, detail="threshold required")
    try:
        v = float(val)
    except Exception:
        raise HTTPException(status_code=400, detail="threshold must be number")
    if not (0.0 <= v <= 1.0):
        raise HTTPException(status_code=400, detail="threshold must be 0.0-1.0")
    cfg_path = Path(config_loader.CONFIG_PATH)
    with open(cfg_path, encoding="utf-8") as f:
        raw = json.load(f)
    raw.setdefault("resume_curation", {})["match_threshold"] = v
    tmp = str(cfg_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)
    os.replace(tmp, cfg_path)
    return {"match_threshold": v}
