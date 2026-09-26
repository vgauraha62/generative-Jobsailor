import os
import hashlib
import json

BASE_MD = "resumes/base.md"
BASE_META = "resumes/base_meta.json"
ACTIVE_JSON = "resumes/active.json"


def _extract_pdf_text_pymupdf(path: str) -> str:
    import pymupdf
    doc = pymupdf.open(path)
    parts = []
    for page in doc:
        parts.append(page.get_text("text") or "")
    return "\n".join(parts)


def _ocr_pdf_via_pymupdf(path: str) -> str:
    import pymupdf
    from PIL import Image
    import pytesseract
    import io
    doc = pymupdf.open(path)
    texts = []
    for page in doc:
        pix = page.get_pixmap(dpi=300)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        texts.append(pytesseract.image_to_string(img))
    return "\n".join(texts)


def ocr_page(path: str, n: int = 0, dpi: int = 200) -> str:
    """OCR one PDF page (default first). Targeted second pass for contact fields."""
    import pymupdf
    from PIL import Image
    import pytesseract
    doc = pymupdf.open(path)
    page = doc[min(n, len(doc) - 1)]
    pix = page.get_pixmap(dpi=dpi)
    return pytesseract.image_to_string(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))


def _extract_docx(path: str) -> str:
    import docx
    d = docx.Document(path)
    return "\n".join(p.text for p in d.paragraphs)


def _extract_tex(path: str) -> str:
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


def _needs_ocr(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 200:
        return True
    words = stripped.split()
    if len(words) < 30:
        return True
    return False


def _normalize_to_md(raw: str, source_name: str) -> str:
    raw = raw.strip()
    if not raw:
        return f"# Resume\n\n*Source: {source_name}*\n\n(empty)\n"
    lines = [l.rstrip() for l in raw.splitlines()]
    md = []
    md.append(f"# Resume — {source_name}\n")
    in_block = False
    for l in lines:
        if not l.strip():
            md.append("")
            continue
        md.append(l)
    return "\n".join(md).strip() + "\n"


def ingest(path: str) -> dict:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        text = _extract_pdf_text_pymupdf(path)
        if _needs_ocr(text):
            try:
                text = _ocr_pdf_via_pymupdf(path)
            except Exception as e:
                print(f"[ingest] OCR fallback failed: {e}")
        raw = text
    elif ext == ".docx":
        raw = _extract_docx(path)
    elif ext == ".doc":
        try:
            raw = _extract_docx(path)
        except Exception:
            import subprocess
            out = subprocess.check_output(["catdoc", path], text=True)
            raw = out
    elif ext in (".tex", ".md", ".txt"):
        raw = _extract_tex(path)
    else:
        raise ValueError(f"unsupported resume type: {ext}")

    md = _normalize_to_md(raw, os.path.basename(path))
    os.makedirs(os.path.dirname(BASE_MD), exist_ok=True)
    with open(BASE_MD, "w", encoding="utf-8") as f:
        f.write(md)
    h = hashlib.sha256(md.encode("utf-8")).hexdigest()[:12]
    meta = {"source": path, "sha": h, "chars": len(md)}
    with open(BASE_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    if os.path.exists(ACTIVE_JSON):
        try:
            with open(ACTIVE_JSON, encoding="utf-8") as f:
                aj = json.load(f)
            if aj.get("sha") != h:
                aj.update({"active_md": BASE_MD, "active_pdf": None, "sha": h})
                with open(ACTIVE_JSON, "w", encoding="utf-8") as af:
                    json.dump(aj, af, indent=2)
        except Exception:
            with open(ACTIVE_JSON, "w", encoding="utf-8") as f:
                json.dump({"active_md": BASE_MD, "active_pdf": None, "sha": h}, f, indent=2)
    else:
        with open(ACTIVE_JSON, "w", encoding="utf-8") as f:
            json.dump({"active_md": BASE_MD, "active_pdf": None, "sha": h}, f, indent=2)
    print(f"[ingest] wrote {BASE_MD} ({len(md)} chars, sha={h})")
    return meta


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python -m resume.ingest <resume.pdf|docx|tex|md>")
        raise SystemExit(1)
    ingest(sys.argv[1])
