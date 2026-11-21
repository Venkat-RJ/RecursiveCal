"""Portable Pandoc AST to ReportLab renderer for the released manuscript."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
from xml.sax.saxutils import escape, quoteattr

from matplotlib import font_manager, mathtext
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def render(root: Path) -> None:
    ast = json.loads(subprocess.check_output([
        "pandoc", "paper/manuscript.md", "--from=markdown", "--citeproc",
        "--bibliography=paper/references.bib", "--to=json"], cwd=root))
    for name, weight, style in [("RCSerif", "normal", "normal"), ("RCSerifBold", "bold", "normal"),
                                ("RCSerifItalic", "normal", "italic"), ("RCSerifBI", "bold", "italic")]:
        path = font_manager.findfont(font_manager.FontProperties(family="DejaVu Serif", weight=weight, style=style))
        pdfmetrics.registerFont(TTFont(name, path))
    pdfmetrics.registerFontFamily("RCSerif", normal="RCSerif", bold="RCSerifBold", italic="RCSerifItalic", boldItalic="RCSerifBI")
    navy = colors.HexColor("#173047")
    body = ParagraphStyle("body", fontName="RCSerif", fontSize=9.6, leading=13.5,
                          alignment=TA_JUSTIFY, spaceAfter=7, allowWidows=0, allowOrphans=0)
    title = ParagraphStyle("title", parent=body, fontName="RCSerifBold", fontSize=20, leading=25,
                           textColor=navy, alignment=TA_CENTER, spaceAfter=15)
    author = ParagraphStyle("author", parent=body, alignment=TA_CENTER, fontSize=10, spaceAfter=5)
    heading = ParagraphStyle("heading", parent=body, fontName="RCSerifBold", fontSize=12, leading=16,
                             textColor=navy, spaceBefore=14, spaceAfter=7, keepWithNext=True)
    subheading = ParagraphStyle("subheading", parent=heading, fontSize=10.3, leading=14, spaceBefore=10)
    caption = ParagraphStyle("caption", parent=body, fontSize=8.4, leading=11.3, textColor=colors.HexColor("#455565"),
                             alignment=0, spaceBefore=6, spaceAfter=13)
    reference = ParagraphStyle("reference", parent=body, fontSize=8.4, leading=11.8, alignment=0, spaceAfter=9)
    cell = ParagraphStyle("cell", parent=body, fontSize=7.8, leading=10.3, alignment=0, spaceAfter=0)
    story = []
    width = 492
    counts = {"section": 0, "subsection": 0, "figure": 0, "equation": 0}

    def inline(items):
        parts = []
        for item in items:
            kind, value = item["t"], item.get("c")
            if kind == "Str":
                parts.append(escape(value.replace("\u2014", " - ")))
            elif kind in ("Space", "SoftBreak", "LineBreak"):
                parts.append(" ")
            elif kind == "Code":
                parts.append('<font name="Courier" size="8.5">' + escape(value[1]) + '</font>')
            elif kind in ("Emph", "Strong", "Superscript", "Subscript"):
                tag = {"Emph": "i", "Strong": "b", "Superscript": "super", "Subscript": "sub"}[kind]
                parts.append(f"<{tag}>" + inline(value) + f"</{tag}>")
            elif kind == "Cite":
                parts.append(inline(value[1]))
            elif kind == "Span":
                parts.append(inline(value[1]))
            elif kind == "Quoted":
                parts.append('"' + inline(value[1]) + '"')
            elif kind == "Link":
                label = inline(value[1])
                url = value[2][0]
                if len(label) > 75 and label.startswith("http"):
                    label = escape(urlsplit(url).netloc + " source record")
                if url.startswith(("https://", "http://")):
                    parts.append("<link href=" + quoteattr(url) + ' color="#245b86">' + label + "</link>")
                else:
                    parts.append(label)
            elif kind == "Math":
                expression = value[1]
                expression = expression.replace("\\times", "×").replace("\\tau", "τ").replace("\\ell", "ℓ")
                expression = re.sub(r"\\(?:operatorname|mathrm)\{([^}]+)\}", r"\1", expression)
                expression = escape(expression)
                expression = re.sub(r"\^\{([^}]+)\}", r"<super>\1</super>", expression)
                expression = re.sub(r"_\{([^}]+)\}", r"<sub>\1</sub>", expression)
                expression = re.sub(r"_([a-zA-Z])", r"<sub>\1</sub>", expression)
                parts.append("<i>" + expression + "</i>")
            else:
                raise ValueError(f"Unsupported manuscript inline: {kind}")
        return "".join(parts)

    def fitted_image(path, max_width=width, max_height=265, native_dpi=None):
        w, h = ImageReader(str(path)).getSize()
        scale = min(max_width / w, max_height / h)
        if native_dpi is not None:
            scale = min(scale, 72 / native_dpi)
        image = Image(str(path), width=w * scale, height=h * scale)
        image.hAlign = "CENTER"
        return image

    def block_text(blocks):
        return " ".join(inline(b["c"]) for b in blocks if b["t"] in ("Para", "Plain"))

    def render_blocks(blocks, selected_style=body):
        for block in blocks:
            kind, value = block["t"], block.get("c")
            if kind == "Header":
                level, _, words = value
                if level == 1:
                    counts["section"] += 1
                    counts["subsection"] = 0
                    text = inline(words)
                    prefix = "" if text == "References" else str(counts["section"]) + ". "
                    story.append(Paragraph(prefix + text, heading))
                else:
                    counts["subsection"] += 1
                    story.append(Paragraph(f"{counts['section']}.{counts['subsection']} " + inline(words), subheading))
            elif kind in ("Para", "Plain"):
                if len(value) == 1 and value[0]["t"] == "Math" and value[0]["c"][0]["t"] == "DisplayMath":
                    counts["equation"] += 1
                    expression = value[0]["c"][1].replace("\n", " ")
                    image_path = root / "paper/figures" / f"equation_{counts['equation']}.png"
                    mathtext.math_to_image("$" + expression + "$", str(image_path), dpi=220,
                                           prop=font_manager.FontProperties(size=13), format="png", color="#172a3b")
                    story.extend([Spacer(1, 4), fitted_image(image_path, max_height=34, native_dpi=220), Spacer(1, 10)])
                else:
                    story.append(Paragraph(inline(value), selected_style))
            elif kind == "Figure":
                counts["figure"] += 1
                image_node = value[2][0]["c"][0]
                image_path = root / "paper" / image_node["c"][2][0]
                cap = "<b>Figure " + str(counts["figure"]) + ".</b> " + block_text(value[1][1])
                story.append(KeepTogether([Spacer(1, 6), fitted_image(image_path), Paragraph(cap, caption)]))
            elif kind == "Table":
                rows = value[3][1] + [row for table_body in value[4] for row in table_body[3]]
                data = [[Paragraph(block_text(c[4]), cell) for c in row[1]] for row in rows]
                widths = [width * .30] + [width * .70 / (len(data[0]) - 1)] * (len(data[0]) - 1)
                table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
                table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf0f3")),
                                           ("LINEBELOW", (0, 0), (-1, 0), .7, navy),
                                           ("LINEBELOW", (0, -1), (-1, -1), .5, navy),
                                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                           ("TOPPADDING", (0, 0), (-1, -1), 6),
                                           ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
                story.append(KeepTogether([Spacer(1, 6), Paragraph("<b>Table 1.</b> Recorded mean net reward.", caption), table, Spacer(1, 12)]))
            elif kind == "Div":
                render_blocks(value[1], reference if "csl-entry" in value[0][1] else selected_style)
            elif kind == "HorizontalRule":
                story.append(Spacer(1, 10))
            else:
                raise ValueError(f"Unsupported manuscript block: {kind}")

    meta = ast["meta"]
    story.append(Paragraph(inline(meta["title"]["c"]), title))
    story.append(Paragraph(inline(meta["author"]["c"]), author))
    story.append(Paragraph(inline(meta["date"]["c"]), author))
    story.append(Spacer(1, 14))
    story.append(Paragraph("Abstract", subheading))
    render_blocks(meta["abstract"]["c"])
    render_blocks(ast["blocks"])

    def page_header(canvas, doc):
        canvas.saveState()
        canvas.setFont("RCSerif", 8)
        canvas.setFillColor(colors.HexColor("#5b6c7b"))
        if doc.page > 1:
            canvas.drawString(60, 757, "RecursiveCal | Research working draft")
        canvas.drawString(60, 35, "21 November 2026 | Synthetic study and software instrument")
        canvas.drawRightString(552, 35, str(doc.page))
        canvas.restoreState()

    output = root / "paper/RecursiveCal_Manuscript.pdf"
    doc = SimpleDocTemplate(str(output), pagesize=(612, 792), leftMargin=60, rightMargin=60,
                            topMargin=52, bottomMargin=54, title="RecursiveCal: Reproducible Diagnostic Selection under Model Mismatch",
                            author="Venkateshwar Reddy")
    doc.build(story, onFirstPage=page_header, onLaterPages=page_header)
    print(f"Built portable PDF: {output}")

