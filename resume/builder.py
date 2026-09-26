import os


def md_to_pdf(md_path: str, pdf_path: str):
    import markdown
    try:
        from weasyprint import HTML
        has_weasy = True
    except Exception:
        has_weasy = False
    with open(md_path, encoding="utf-8") as f:
        md_text = f.read()
    html_body = markdown.markdown(md_text, extensions=["extra"])
    html = f"<html><head><meta charset='utf-8'><style>body{{font-family: sans-serif; font-size: 11pt; line-height:1.4; margin: 40px;}} h1{{font-size:16pt}} h2{{font-size:13pt; margin-top:18px}} li{{margin-bottom:4px}}</style></head><body>{html_body}</body></html>"
    os.makedirs(os.path.dirname(pdf_path) or ".", exist_ok=True)
    if has_weasy:
        HTML(string=html).write_pdf(pdf_path)
    else:
        from fpdf import FPDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_font("Helvetica", size=10)
        for line in md_text.splitlines():
            pdf.multi_cell(0, 5, line)
        pdf.output(pdf_path)
    return pdf_path
