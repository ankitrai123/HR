"""Report exporters: plain text, JSON and PDF."""
from __future__ import annotations

import json
from typing import Any, Mapping

from fpdf import FPDF

from hybrid_assessment_engine import public_report

NAVY = (26, 54, 93)
BLUE = (37, 99, 235)
GREY = (100, 116, 139)
LEVEL_COLOURS = {"Low": (217, 119, 6), "Moderate": (100, 116, 139), "High": (22, 163, 74)}


def to_json(report: Mapping[str, Any]) -> str:
    return json.dumps(public_report(report), indent=2, ensure_ascii=False)


def to_text(report: Mapping[str, Any]) -> str:
    lines = [
        "PERSONALITY ASSESSMENT REPORT",
        "=" * 60,
        f"Candidate: {report['name']}   ID: {report['test_id']}",
        f"Status: {report['status']}   Response quality: {report['response_quality']}",
    ]
    if report.get("quality_flags"):
        lines += ["Quality flags:"] + [f"  - {f}" for f in report["quality_flags"]]
    lines += ["", "SUMMARY", "-" * 60, report.get("profile_summary", ""), ""]

    scores = report.get("scores") or {}
    if scores:
        lines += ["SCORES", "-" * 60]
        for dim, s in scores.items():
            bar = "#" * s["sten_score"] + "." * (10 - s["sten_score"])
            lines.append(f"{dim:26s} [{bar}] Sten {s['sten_score']:>2}  {s['level']:<8}  P{s['percentile']:.0f}")
            lines.append(f"    {s['interpretation']}")
        lines.append("")

    premium = report.get("premium_features")
    if premium and "executive_summary" in premium:
        lines += ["EXECUTIVE SUMMARY", "-" * 60, premium["executive_summary"], "", "DEVELOPMENT PLAN", "-" * 60]
        for item in premium["development_plan"]:
            lines.append(f"{item['dimension']}:")
            lines += [f"  - {a}" for a in item["actions"]]
        lines += ["", "COACHING INSIGHTS", "-" * 60] + [f"- {c}" for c in premium["coaching_insights"]]
    if report.get("norms") == "provisional":
        lines += ["", "Note: Sten scores use provisional norms and should not be used for selection decisions."]
    return "\n".join(lines) + "\n"


class _ReportPDF(FPDF):
    def header(self) -> None:
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*NAVY)
        self.cell(0, 8, "Personality Assessment Report", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(226, 232, 240)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*GREY)
        self.cell(0, 10, f"Confidential - page {self.page_no()}", align="C")


def _safe(text: str) -> str:
    """Core PDF fonts are Latin-1 only; swap common Unicode punctuation."""
    table = {"—": "-", "–": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "..."}
    for k, v in table.items():
        text = text.replace(k, v)
    return text.encode("latin-1", "replace").decode("latin-1")


def to_pdf(report: Mapping[str, Any]) -> bytes:
    pdf = _ReportPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin

    def heading(text: str) -> None:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(*NAVY)
        pdf.cell(0, 8, _safe(text), new_x="LMARGIN", new_y="NEXT")

    def para(text: str, size: float = 10, colour: tuple[int, int, int] = (15, 23, 42)) -> None:
        pdf.set_font("Helvetica", "", size)
        pdf.set_text_color(*colour)
        pdf.multi_cell(width, 5, _safe(text), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 10, _safe(report["name"]), new_x="LMARGIN", new_y="NEXT")
    para(f"Candidate ID {report['test_id']}  |  {report['status']}  |  Response quality: {report['response_quality']}",
         9, GREY)
    for flag in report.get("quality_flags") or []:
        para(f"! {flag}", 9, LEVEL_COLOURS["Low"])

    heading("Summary")
    para(report.get("profile_summary", ""))

    scores = report.get("scores") or {}
    if scores:
        heading("Dimension scores")
        for dim, s in scores.items():
            y = pdf.get_y()
            if y > pdf.h - 45:
                pdf.add_page()
                y = pdf.get_y()
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(15, 23, 42)
            pdf.cell(62, 6, _safe(dim))
            # Sten bar: 10 cells, filled up to the score.
            for i in range(10):
                pdf.set_fill_color(*(BLUE if i < s["sten_score"] else (226, 232, 240)))
                pdf.rect(pdf.l_margin + 62 + i * 7, y + 1, 6, 4, style="F")
            pdf.set_xy(pdf.l_margin + 136, y)
            pdf.set_text_color(*LEVEL_COLOURS[s["level"]])
            pdf.cell(0, 6, f"Sten {s['sten_score']}  {s['level']}", new_x="LMARGIN", new_y="NEXT")
            para(s["interpretation"], 9, GREY)
            pdf.ln(1.5)

    premium = report.get("premium_features")
    if premium and "executive_summary" in premium:
        heading("Executive summary")
        para(premium["executive_summary"])
        heading("Development plan")
        for item in premium["development_plan"]:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(15, 23, 42)
            pdf.cell(0, 6, _safe(item["dimension"]), new_x="LMARGIN", new_y="NEXT")
            for action in item["actions"]:
                para(f"- {action}", 9.5)
        heading("Coaching insights")
        for insight in premium["coaching_insights"]:
            para(f"- {insight}", 9.5)

    if report.get("norms") == "provisional":
        pdf.ln(4)
        para("Sten scores are calculated against provisional norms and should not be used for selection decisions "
             "until norms are calibrated on a representative candidate sample.", 8, GREY)
    return bytes(pdf.output())
