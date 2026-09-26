import os
import hashlib


def curate_md(base_md: str, jd_text: str, timeout=40) -> str:
    from gemini_api import bard_flash_response_curation
    prompt = (
        "You are rewriting a resume in markdown. Curate EVERY section that benefits from JD keywords: "
        "intro, summary, skills, work descriptions. Keep one-liner bullets truthful — do not invent experience. "
        "Inject missing JD keywords naturally. Return ONLY the full curated markdown, no fence, no commentary.\n\n"
        f"BASE RESUME (markdown):\n{base_md[:8000]}\n\n"
        f"JOB DESCRIPTION:\n{jd_text[:6000]}\n"
    )
    out = bard_flash_response_curation(prompt, timeout)
    cleaned = out.strip().removeprefix("```markdown").removeprefix("```").removesuffix("```").strip()
    return cleaned if len(cleaned) > 200 else base_md


def save_curated(curated_md: str, jd_text: str, out_dir="resumes/curated") -> tuple:
    os.makedirs(out_dir, exist_ok=True)
    h = hashlib.sha256(jd_text.encode("utf-8")).hexdigest()[:10]
    md_path = os.path.join(out_dir, f"{h}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(curated_md)
    return md_path, h
