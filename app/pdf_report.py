"""Professional, evidence-based AutoGrader technical evaluation dossier."""

import math
import os
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table,
    TableStyle, KeepTogether, HRFlowable, Preformatted,
)
from reportlab.graphics.shapes import Drawing, String, Rect, Line
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.graphics.charts.piecharts import Pie


NAVY = colors.HexColor("#880000")
BLUE = colors.HexColor("#cc7755")
CYAN = colors.HexColor("#d89a76")
GREEN = colors.HexColor("#789922")
RED = colors.HexColor("#b33a3a")
AMBER = colors.HexColor("#b97725")
GREY = colors.HexColor("#70645e")
PURPLE = colors.HexColor("#8b5483")
LIGHT = colors.HexColor("#f0e0d6")
DARK = colors.HexColor("#2d211d")
WHITE = colors.HexColor("#ffffee")

FONT = "Helvetica"
BOLD = "Helvetica-Bold"
MONO = "Courier"
ASCII_DASHES = str.maketrans({
    "\u2010": "-", "\u2011": "-", "\u2012": "-",
    "\u2013": "-", "\u2014": "-", "\u2015": "-",
    "\u2212": "-", "\ufe58": "-", "\ufe63": "-", "\uff0d": "-",
})


def _register_fonts():
    global FONT, BOLD
    candidates = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
    ]
    for regular, bold in candidates:
        if os.path.exists(regular) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont("AutoSans", regular))
                pdfmetrics.registerFont(TTFont("AutoSans-Bold", bold))
                FONT, BOLD = "AutoSans", "AutoSans-Bold"
                return
            except Exception:
                pass


def _find(data, names, default=None):
    """Find the first matching key recursively in nested evaluation data."""
    if not isinstance(data, dict):
        return default
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    for value in data.values():
        if isinstance(value, dict):
            result = _find(value, names, None)
            if result is not None:
                return result
    return default


def _human_value(value, depth=0):
    if value is None:
        return "Not available"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, dict):
        if depth >= 2:
            return "Additional details available"
        parts = []
        for key, item in value.items():
            label = str(key).replace("_", " ").strip().capitalize()
            parts.append(f"{label}: {_human_value(item, depth + 1)}")
        return "; ".join(parts)
    if isinstance(value, (list, tuple)):
        if not value:
            return "None"
        return "; ".join(_human_value(item, depth + 1) for item in value[:20])
    return str(value)


def _safe(value, limit=10000):
    if value is None:
        return "Not available"
    text = _human_value(value).translate(ASCII_DASHES)[:limit]
    return escape(text).replace("\\n", "<br/>").replace("  ", "&nbsp;&nbsp;")


def _p(value, style):
    return Paragraph(_safe(value), style)


def _flatten_items(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("findings", "items", "results", "cases", "tests"):
            if isinstance(value.get(key), list):
                return value[key]
    return []


def _table(rows, widths, styles, header=True):
    converted = []
    for r_index, row in enumerate(rows):
        converted.append([
            Paragraph(
                str(cell) if isinstance(cell, Paragraph) else _safe(cell, 3000),
                styles["table_header"] if header and r_index == 0 else styles["table_cell"],
            )
            for cell in row
        ])
    t = Table(converted, colWidths=widths, repeatRows=1 if header else 0,
              hAlign="LEFT")
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#ddc8bb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    if header:
        commands += [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
        ]
    else:
        commands.append(("ROWBACKGROUNDS", (0, 0), (-1, -1), [WHITE, LIGHT]))
    t.setStyle(TableStyle(commands))
    return t


def _bar_chart(title, labels, values, width=470, height=205):
    drawing = Drawing(width, height)
    drawing.add(String(8, height - 17, title, fontName=BOLD,
                       fontSize=10, fillColor=NAVY))
    chart = VerticalBarChart()
    chart.x, chart.y = 45, 35
    chart.width, chart.height = width - 65, height - 65
    chart.data = [values]
    chart.categoryAxis.categoryNames = labels
    chart.categoryAxis.labels.fontName = FONT
    chart.categoryAxis.labels.fontSize = 7
    chart.categoryAxis.labels.angle = 0
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = max(1, max(values) * 1.2)
    chart.valueAxis.labels.fontName = FONT
    chart.valueAxis.labels.fontSize = 7
    chart.bars[0].fillColor = BLUE
    chart.bars[0].strokeColor = BLUE
    chart.barWidth = min(30, max(10, 240 / max(1, len(values))))
    drawing.add(chart)
    return drawing



def _line_chart(title, points, width=470, height=220):
    """Render empirical input-size/runtime observations."""
    drawing = Drawing(width, height)
    drawing.add(String(8, height - 17, title, fontName=BOLD,
                       fontSize=10, fillColor=NAVY))

    chart = LinePlot()
    chart.x, chart.y = 52, 38
    chart.width, chart.height = width - 75, height - 72
    chart.data = [points]
    chart.joinedLines = 1
    chart.lines[0].strokeColor = BLUE
    chart.lines[0].strokeWidth = 1.8
    chart.lines[0].symbol = makeMarker("Circle")
    chart.lines[0].symbol.size = 4

    chart.xValueAxis.valueMin = min(point[0] for point in points)
    chart.xValueAxis.valueMax = max(point[0] for point in points)
    chart.xValueAxis.labelTextFormat = "%.0f"
    chart.xValueAxis.labels.fontName = FONT
    chart.xValueAxis.labels.fontSize = 7
    chart.xValueAxis.visibleGrid = 1

    chart.yValueAxis.valueMin = 0
    chart.yValueAxis.valueMax = max(
        max(point[1] for point in points) * 1.2, 0.000001
    )
    chart.yValueAxis.labelTextFormat = "%.4f"
    chart.yValueAxis.labels.fontName = FONT
    chart.yValueAxis.labels.fontSize = 7
    chart.yValueAxis.visibleGrid = 1

    drawing.add(chart)
    return drawing



def _multi_program_runtime_chart(title, measurements, width=470, height=245):
    """Plot successful measured runtimes for each implementation."""
    names = ("student", "brute_force", "efficient")
    labels = {
        "student": "Student",
        "brute_force": "Brute-force",
        "efficient": "Efficient",
    }
    palette = (RED, BLUE, GREEN)
    grouped = {name: [] for name in names}

    for item in measurements:
        if not isinstance(item, dict):
            continue
        name = item.get("program")
        x = item.get("input_size")
        y = item.get("runtime_seconds")
        if (
            name in grouped
            and isinstance(x, (int, float)) and not isinstance(x, bool)
            and x >= 0
            and isinstance(y, (int, float)) and not isinstance(y, bool)
            and y >= 0
        ):
            grouped[name].append((float(x), float(y)))

    grouped = {
        name: sorted(points)
        for name, points in grouped.items()
        if points
    }
    if not grouped:
        return None

    drawing = Drawing(width, height)
    drawing.add(String(8, height - 14, title, fontName=BOLD, fontSize=10))
    chart = LinePlot()
    chart.x = 55
    chart.y = 48
    chart.width = width - 85
    chart.height = height - 95
    chart.data = [grouped[name] for name in names if name in grouped]
    chart.joinedLines = 1

    for index, name in enumerate(name for name in names if name in grouped):
        line = chart.lines[index]
        line.strokeColor = palette[names.index(name)]
        line.strokeWidth = 1.8
        line.symbol = makeMarker("Circle")
        line.symbol.size = 4

    all_points = [point for points in grouped.values() for point in points]
    xs = [point[0] for point in all_points]
    ys = [point[1] for point in all_points]
    xmin, xmax = min(xs), max(xs)
    chart.xValueAxis.valueMin = xmin
    chart.xValueAxis.valueMax = xmax if xmax > xmin else xmin + 1
    chart.xValueAxis.labelTextFormat = "%.0f"
    chart.xValueAxis.labels.fontName = FONT
    chart.xValueAxis.labels.fontSize = 7
    chart.xValueAxis.visibleGrid = 1
    chart.yValueAxis.valueMin = 0
    chart.yValueAxis.valueMax = max(max(ys) * 1.2, 0.000001)
    chart.yValueAxis.labelTextFormat = "%.4f"
    chart.yValueAxis.labels.fontName = FONT
    chart.yValueAxis.labels.fontSize = 7
    chart.yValueAxis.visibleGrid = 1
    drawing.add(chart)

    legend_x = 65
    for index, name in enumerate(name for name in names if name in grouped):
        x = legend_x + index * 125
        drawing.add(Rect(x, 12, 9, 7, fillColor=palette[names.index(name)], strokeColor=None))
        drawing.add(String(x + 13, 11, labels[name], fontName=FONT, fontSize=7))

    drawing.add(String(width / 2 - 42, 27, "Input size (actual n)", fontName=FONT, fontSize=7))
    drawing.add(String(5, height / 2, "Runtime (seconds)", fontName=FONT, fontSize=7))
    return drawing


def _complexity_curve_chart(graph, label, width=470, height=220):
    """Draw the adaptive generic growth curve returned by the math engine."""
    if not isinstance(graph, dict) or graph.get("status") != "completed":
        return None
    points = graph.get("points")
    if not isinstance(points, list) or len(points) < 2:
        return None
    valid = [
        (float(item["x"]), float(item["y"]))
        for item in points
        if isinstance(item, dict)
        and isinstance(item.get("x"), (int, float))
        and not isinstance(item.get("x"), bool)
        and item["x"] > 0
        and isinstance(item.get("y"), (int, float))
        and not isinstance(item.get("y"), bool)
        and math.isfinite(item["x"])
        and math.isfinite(item["y"])
    ]
    if len(valid) < 2:
        return None
    drawing = Drawing(width, height)
    drawing.add(String(8, height - 16, f"{label}: {graph.get('original_notation', '')}",
                       fontName=BOLD, fontSize=9, fillColor=NAVY))
    left, right, bottom, top = 50, width - 12, 32, height - 36
    xs = [math.log10(point[0]) for point in valid]
    ys = [point[1] for point in valid]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    if max_x == min_x:
        max_x = min_x + 1
    if max_y == min_y:
        max_y = min_y + 1
    def xy(point):
        px = left + (math.log10(point[0]) - min_x) / (max_x - min_x) * (right - left)
        py = bottom + (point[1] - min_y) / (max_y - min_y) * (top - bottom)
        return px, py
    drawing.add(Line(left, bottom, right, bottom, strokeColor=GREY, strokeWidth=.7))
    drawing.add(Line(left, bottom, left, top, strokeColor=GREY, strokeWidth=.7))
    ordered = sorted(valid)
    for first, second in zip(ordered, ordered[1:]):
        x1, y1 = xy(first)
        x2, y2 = xy(second)
        drawing.add(Line(x1, y1, x2, y2, strokeColor=PURPLE, strokeWidth=1.8))
    for point in ordered:
        px, py = xy(point)
        drawing.add(Rect(px - 1.5, py - 1.5, 3, 3, fillColor=PURPLE, strokeColor=None))
    drawing.add(String(width / 2 - 42, 8, "log10(generic input size n)",
                       fontName=FONT, fontSize=7, fillColor=GREY))
    y_label = (graph.get("axis") or {}).get("y_label", "Representative growth")
    drawing.add(String(4, height / 2, str(y_label)[:50],
                       fontName=FONT, fontSize=6, fillColor=GREY))
    return drawing


def _pie_chart(title, labels, values, width=470, height=210):
    drawing = Drawing(width, height)
    drawing.add(String(8, height - 17, title, fontName=BOLD,
                       fontSize=10, fillColor=NAVY))
    pie = Pie()
    pie.x, pie.y = 20, 15
    pie.width, pie.height = 165, 165
    pie.data = values
    pie.labels = labels
    pie.sideLabels = True
    pie.simpleLabels = False
    pie.slices.strokeWidth = 0.5
    palette = [GREEN, RED, AMBER, BLUE, CYAN]
    for i in range(len(values)):
        pie.slices[i].fillColor = palette[i % len(palette)]
    drawing.add(pie)
    return drawing


def _section(story, title, subtitle, styles):
    # Keep thematic pairs together across pages instead of letting section
    # headings land at the bottom of a page after unrelated material.
    if str(title).startswith(("04  /", "06  /", "07  /", "08  /", "10  /")):
        story.append(PageBreak())
    story.append(Spacer(1, 3 * mm))
    heading = [Paragraph(escape(str(title).translate(ASCII_DASHES)), styles["section"])]
    if subtitle:
        heading.append(Paragraph(escape(str(subtitle).translate(ASCII_DASHES)), styles["subtitle"]))
    heading.append(HRFlowable(width="100%", thickness=1, color=NAVY,
                              spaceBefore=2, spaceAfter=8))
    story.append(KeepTogether(heading))


def _metric_cards(metrics, styles):
    cells = []
    for label, value in metrics:
        cells.append([
            Paragraph(_safe(value), styles["metric_value"]),
            Paragraph(_safe(label), styles["metric_label"]),
        ])
    t = Table([cells], colWidths=[168 * mm / max(1, len(cells))] * len(cells))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#ddc8bb")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, WHITE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def _draw_page(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(WHITE)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    if doc.page > 1:
        canvas.setStrokeColor(colors.HexColor("#ddc8bb"))
        canvas.line(18 * mm, height - 13 * mm, width - 18 * mm, height - 13 * mm)
        canvas.setFont(FONT, 7)
        canvas.setFillColor(GREY)
        canvas.drawString(18 * mm, height - 10 * mm, "AUTOGRADER  /  TECHNICAL EVALUATION")
        canvas.drawRightString(width - 18 * mm, height - 10 * mm, "C PROGRAM REVIEW")
    canvas.setStrokeColor(colors.HexColor("#ddc8bb"))
    canvas.line(18 * mm, 13 * mm, width - 18 * mm, 13 * mm)
    canvas.setFont(FONT, 7)
    canvas.setFillColor(GREY)
    canvas.drawString(18 * mm, 8 * mm, "Evidence-based report · Heuristic findings are not proof")
    canvas.drawRightString(width - 18 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _final_grade_graph(grading: dict[str, Any], width: float = 470, height: float = 196):
    """Draw a compact scorecard with a dominant grade and weighted metric bars."""
    drawing = Drawing(width, height)
    score = grading.get("score")
    band = grading.get("grade_band") or "-"
    status = "FINAL GRADE" if grading.get("score") is not None else "MORE EVIDENCE NEEDED"
    drawing.add(Rect(0, 0, 136, height, fillColor=NAVY, strokeColor=None))
    drawing.add(String(17, height - 29, "FINAL GRADE", fontName=BOLD, fontSize=9, fillColor=WHITE))
    drawing.add(String(18, height - 105, str(band), fontName=BOLD, fontSize=43, fillColor=colors.HexColor("#F1CF75")))
    drawing.add(String(18, height - 132, (f"{score} / 100" if score is not None else "Not gradeable"), fontName=BOLD, fontSize=12, fillColor=WHITE))
    drawing.add(String(18, 18, status, fontName=BOLD, fontSize=8, fillColor=colors.HexColor("#D7E7EF")))

    breakdown = grading.get("breakdown") if isinstance(grading.get("breakdown"), dict) else {}
    ordered = sorted(breakdown.items(), key=lambda pair: (-float(pair[1].get("weight", 0) or 0), pair[0]))
    row_height = 22
    top = height - 24
    bar_x, bar_width = 248, width - 300
    for index, (name, item) in enumerate(ordered[:7]):
        y = top - index * row_height
        label = {"mathematical_correctness": "Math correctness", "design_originality": "Novelty of thought"}.get(name, name.replace("_", " ").title())
        value = item.get("score")
        score_text = "N/A" if value is None else f"{value:g}"
        drawing.add(String(148, y, label, fontName=BOLD, fontSize=7.1, fillColor=NAVY))
        drawing.add(Rect(bar_x, y - 3, bar_width, 8, fillColor=LIGHT, strokeColor=None))
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            color = GREEN if value >= 75 else AMBER if value >= 50 else RED
            drawing.add(Rect(bar_x, y - 3, bar_width * max(0, min(100, float(value))) / 100, 8, fillColor=color, strokeColor=None))
        drawing.add(String(width - 37, y - 1, score_text, fontName=BOLD, fontSize=8, fillColor=DARK))
        drawing.add(String(bar_x, y - 11, f"weight {item.get('weight', 0)}%", fontName=FONT, fontSize=6.5, fillColor=GREY))
    return drawing


def generate_pdf_report(evaluation: dict[str, Any], output_path: str | Path) -> Path:
    """Generate a multi-section report with evidence-derived charts."""
    if not isinstance(evaluation, dict):
        raise TypeError("evaluation must be a dictionary")

    _register_fonts()
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="CoverTitle", fontName=BOLD, fontSize=27, leading=34,
        textColor=NAVY, alignment=TA_CENTER, spaceAfter=12,
    ))
    styles.add(ParagraphStyle(
        name="CoverSub", fontName=FONT, fontSize=11, leading=17,
        textColor=GREY, alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        name="section", fontName=BOLD, fontSize=18, leading=23,
        textColor=NAVY, spaceAfter=5,
    ))
    styles.add(ParagraphStyle(
        name="subtitle", fontName=FONT, fontSize=9, leading=13,
        textColor=GREY, spaceAfter=5,
    ))
    styles.add(ParagraphStyle(
        name="body_custom", fontName=FONT, fontSize=8.5, leading=13,
        textColor=DARK, spaceAfter=6, splitLongWords=True,
    ))
    styles.add(ParagraphStyle(
        name="table_cell", fontName=FONT, fontSize=7.3, leading=10,
        textColor=DARK, splitLongWords=True,
    ))
    styles.add(ParagraphStyle(
        name="table_header", fontName=BOLD, fontSize=7.5, leading=10,
        textColor=WHITE,
    ))
    styles.add(ParagraphStyle(
        name="metric_value", fontName=BOLD, fontSize=17, leading=21,
        textColor=NAVY, alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        name="metric_label", fontName=FONT, fontSize=7, leading=10,
        textColor=GREY, alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        name="math", fontName=MONO, fontSize=8, leading=13,
        leftIndent=10, borderColor=colors.HexColor("#D8DEE8"),
        borderWidth=0.5, borderPadding=7, backColor=LIGHT,
        spaceBefore=4, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="small", fontName=FONT, fontSize=7, leading=10,
        textColor=GREY,
    ))

    doc = SimpleDocTemplate(
        str(destination), pagesize=A4,
        rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=20 * mm, bottomMargin=19 * mm,
        title="AutoGrader - Comprehensive Technical Evaluation",
        author="AutoGrader",
        subject="C program evaluation, testing, complexity and verification",
    )

    grading = evaluation.get("grading") or {}
    tests = _find(evaluation, ("test_evaluation", "test_results", "tests", "test_summary"), {}) or {}
    complexity = evaluation.get("complexity_estimate") or _find(evaluation, ("complexity",), {}) or {}
    quality = _find(evaluation, ("code_quality", "quality_analysis"), {}) or {}
    verification = _find(
        evaluation, ("verification", "mathematical_verification", "agent5")
    ) or {}
    preflight = evaluation.get("preflight") or {}
    reconstruction = evaluation.get("reconstruction") or {}
    references = evaluation.get("references") or evaluation.get("reference_solutions") or {}
    execution = evaluation.get("execution_evidence_summary") or evaluation.get("execution_summary") or evaluation.get("execution_evidence") or {}

    passed = _find(tests, ("passed",), None)
    failed = _find(tests, ("failed",), None)
    inconclusive = _find(tests, ("inconclusive",), None)
    quality_score = quality.get("score") if isinstance(quality, dict) else None

    story = []
    if evaluation.get("demo_mode") is True:
        scenario_name = escape(str(evaluation.get("demo_scenario_name") or evaluation.get("demo_scenario_id") or "Demo scenario"))
        story += [
            Paragraph("DEMO MODE - SIMULATED AI ANALYSIS / REAL EXECUTION", styles["section"]),
            Paragraph(
                f"Scenario: {scenario_name}. AI responses are predefined. Compilation, "
                "input validation, C execution, reference checks and benchmark measurements "
                "were performed by the local pipeline.",
                styles["body_custom"],
            ),
            Spacer(1, 6 * mm),
        ]

    # COVER
    story += [
        Spacer(1, 34 * mm),
        Paragraph("AUTOGRADER", styles["CoverTitle"]),
        Paragraph("CODE REVIEW &amp; ALGORITHM<br/>REPORT", styles["CoverTitle"]),
        Spacer(1, 7 * mm),
        Paragraph("C PROGRAM REVIEW  ·  TEST EVIDENCE  ·  REPRODUCIBLE SCORE", styles["CoverSub"]),
        Spacer(1, 22 * mm),
        HRFlowable(width="55%", thickness=2, color=BLUE,
                   hAlign="CENTER", spaceAfter=18),
        Paragraph(
            "A concise summary of the submission, its observed behavior, algorithmic "
            "cost, code review, and final reproducible grade.",
            styles["CoverSub"],
        ),
        Spacer(1, 25 * mm),
        _metric_cards([
            ("Passed tests", passed if passed is not None else "Not available"),
            ("Failed tests", failed if failed is not None else "Not available"),
            ("Grade", (f"{grading.get('grade_band', '')} · {grading.get('score')} / 100" if isinstance(grading, dict) and grading.get("score") is not None else (grading.get("status", "Not graded") if isinstance(grading, dict) else "Not graded"))),
        ], styles),
        Spacer(1, 20 * mm),
        Paragraph(
            "Generated: " + datetime.now(timezone.utc).strftime("%d %B %Y · %H:%M UTC"),
            styles["CoverSub"],
        ),
        PageBreak(),
    ]

    # EXECUTIVE SUMMARY
    story += [
        Paragraph("01  /  EXECUTIVE SUMMARY", styles["section"]),
        Paragraph(
            "This summary reflects the evidence collected for this submission. "
            "Timeouts and infrastructure errors are inconclusive; AI proof sketches "
            "are not machine-checked proofs.",
            styles["body_custom"],
        ),
    ]

    summary_rows = [["Evaluation evidence", "Result"]]
    for label, value in [
        ("Test cases passed", passed),
        ("Test cases failed", failed),
        ("Inconclusive test cases", inconclusive),
        ("Code review score", quality_score),
    ]:
        summary_rows.append([label, value if value is not None else "Not available"])
    story.append(_table(summary_rows, [65 * mm, 103 * mm], styles))

    # 02 PREFLIGHT
    if ((isinstance(preflight, dict) and (preflight.get("summary") or preflight.get("message")))
            or evaluation.get("source_risks")):
        _section(story, "02  /  INTAKE & PREFLIGHT", "Source checks", styles)
    if isinstance(preflight, dict):
        preflight_summary = preflight.get("summary") or preflight.get("message")
        if preflight_summary:
            story.append(Paragraph(_safe(preflight_summary), styles["body_custom"]))
    source_risks = evaluation.get("source_risks")
    if source_risks:
        story.append(Paragraph("Source-risk findings", styles["Heading2"]))
        items = _flatten_items(source_risks)
        if items:
            rows = [["Rule", "Severity", "Finding"]]
            for item in items:
                if isinstance(item, dict):
                    rows.append([
                        item.get("rule", item.get("category", "Finding")),
                        item.get("severity", "Unspecified"),
                        item.get("message", item.get("description", item)),
                    ])
            story.append(_table(rows, [38 * mm, 28 * mm, 102 * mm], styles))
        else:
            story.append(Paragraph(_safe(source_risks), styles["body_custom"]))

    # 03 RECONSTRUCTION
    _section(story, "03  /  PROBLEM RECONSTRUCTION", "Agent 1 · Reconstructed task and assignment constraints.", styles)
    if isinstance(reconstruction, dict):
        candidates = reconstruction.get("candidates", [])
        if isinstance(candidates, list):
            for index, candidate in enumerate(candidates[:3], 1):
                if not isinstance(candidate, dict):
                    continue
                title = candidate.get("title", candidate.get("problem_statement", f"Candidate {index}"))
                story.append(Paragraph(f"<b>Candidate {index}:</b> {escape(str(title))}", styles["Heading2"]))
                for label, key in (("Problem", "problem_statement"), ("Input", "input_format"), ("Output", "output_format")):
                    value = candidate.get(key)
                    if value:
                        story.append(Paragraph(f"<b>{label}:</b> {escape(str(value))}", styles["body_custom"]))
        constraints = reconstruction.get("constraints", [])
        if isinstance(constraints, list) and constraints:
            story.append(Paragraph("<b>Constraints:</b> " + escape(" · ".join(map(str, constraints[:12]))), styles["body_custom"]))
    spec = evaluation.get("assignment_spec")
    if isinstance(spec, dict):
        schema = spec.get("input_schema")
        if isinstance(schema, dict) and isinstance(schema.get("fields"), list):
            rows = [["Input field", "Type and bounds"]]
            for field in schema["fields"][:12]:
                if not isinstance(field, dict):
                    continue
                details = [str(field.get("type", "value"))]
                if field.get("min") is not None: details.append(f"min {field['min']}")
                if field.get("max") is not None: details.append(f"max {field['max']}")
                if field.get("length_from"): details.append(f"length from {field['length_from']}")
                rows.append([field.get("name", "field"), ", ".join(details)])
            story.append(Paragraph("Confirmed input schema", styles["Heading2"]))
            story.append(_table(rows, [55 * mm, 113 * mm], styles))

    # 04 REFERENCES
    _section(story, "04  /  REFERENCE SOLUTIONS", "Agent 2 · Algorithm summaries and oracle validation state.", styles)
    if isinstance(references, dict):
        trusted = references.get("references_trusted", references.get("refs_trusted", False))
        story.append(Paragraph(
            "<b>Oracle trust:</b> " + ("Validated for this specification" if trusted is True else "Unverified; benchmark comparisons are evidence, not certified truth"),
            styles["body_custom"],
        ))
        rows = [["Approach", "Algorithm", "Time", "Space"]]
        for key, label in (("brute_force", "Brute force"), ("efficient", "Efficient")):
            item = references.get(key)
            if not isinstance(item, dict):
                continue
            rows.append([label, item.get("algorithm", "Not supplied"), item.get("time_complexity", "Not supplied"), item.get("space_complexity", "Not supplied")])
        if len(rows) > 1:
            story.append(_table(rows, [27 * mm, 75 * mm, 33 * mm, 33 * mm], styles))
        limitations = references.get("limitations")
        if isinstance(limitations, list) and limitations:
            story.append(Paragraph("<b>Reference limitations:</b> " + escape(" · ".join(map(str, limitations[:3]))), styles["small"]))

    # 05 TESTING
    _section(story, "05  /  TEST GENERATION & EXECUTION", "Agent 3A and 3B · Generated cases and execution observations.", styles)
    if isinstance(tests, dict):
        story.append(Paragraph("Explicit test evaluation", styles["Heading2"]))
        rows = [["Test metric", "Count"]]
        for label, value in [
            ("Passed", passed), ("Failed", failed), ("Inconclusive", inconclusive),
            ("Total", _find(tests, ("total", "total_tests"), None)),
        ]:
            if value is not None:
                rows.append([label, value])
        if len(rows) > 1:
            story.append(_table(rows, [65 * mm, 103 * mm], styles))

        case_results = tests.get("results", [])
        if isinstance(case_results, list) and case_results:
            failures = [item for item in case_results if isinstance(item, dict) and item.get("failed") is True][:5]
            if failures:
                story.append(Paragraph("Confirmed failing cases (up to five)", styles["Heading2"]))
                case_rows = [["Case", "Input", "Expected", "Student output", "Execution"]]
                for index, item in enumerate(failures, 1):
                    case_rows.append([
                        item.get("case", index),
                        str(item.get("input", ""))[:350],
                        str(item.get("expected_output", ""))[:250],
                        str(item.get("actual_output", ""))[:250],
                        item.get("execution_class", item.get("status", "failed")),
                    ])
                story.append(_table(case_rows, [12 * mm, 56 * mm, 31 * mm, 38 * mm, 31 * mm], styles))
            else:
                story.append(Paragraph(
                    f"No confirmed wrong outputs among {len(case_results)} explicit cases. "
                    f"{inconclusive or 0} case(s) were inconclusive; their inputs are omitted.",
                    styles["small"],
                ))

    if isinstance(execution, dict):
        story.append(Paragraph("Additional execution observations", styles["Heading2"]))
        observation_rows = [["Execution group", "Status", "Executed", "Observed outcomes"]]
        for key, label in (
            ("random_tests", "Random tests"),
            ("adversarial_tests", "Adversarial tests"),
        ):
            group = execution.get(key)
            if isinstance(group, dict):
                counts = group.get("outcome_counts") or {}
                observation_rows.append([
                    label,
                    group.get("status", "Not available"),
                    group.get("executed", "Not available"),
                    ", ".join(f"{str(name).replace('_', ' ')}: {value}" for name, value in sorted(counts.items())) if isinstance(counts, dict) else "Not available",
                ])
        if len(observation_rows) > 1:
            story.append(_table(
                observation_rows,
                [30 * mm, 32 * mm, 25 * mm, 81 * mm],
                styles,
            ))
        if execution.get("interpretation"):
            story.append(Paragraph(_safe(execution["interpretation"]), styles["body_custom"]))
        story.append(Paragraph(
            "Random and adversarial execution outcomes are observations. "
            "Without trusted expected outputs, they do not establish correctness "
            "and do not contribute to the correctness score.",
            styles["body_custom"],
        ))

    memory = evaluation.get("memory_safety")
    memory_results = memory.get("results") if isinstance(memory, dict) else None
    if isinstance(memory_results, dict) and memory_results:
        story.append(Paragraph("Runtime memory checks", styles["Heading2"]))
        memory_rows = [["Tool", "Result"]]
        for key, item in memory_results.items():
            if not isinstance(item, dict):
                continue
            status = item.get("status")
            label = (
                "No issue detected on the sampled input" if status == "no_issue_detected_on_this_input"
                else "Potential issue reported" if status == "diagnostic_finding"
                else "Unavailable" if status == "unavailable"
                else "Check did not complete"
            )
            memory_rows.append(["AddressSanitizer + UBSan" if key == "asan" else key.title(), label])
        if len(memory_rows) > 1:
            story.append(_table(memory_rows, [52 * mm, 116 * mm], styles))
            story.append(Paragraph(
                "Both tools inspect one representative test input. A clean sampled run does not prove general memory safety.",
                styles["small"],
            ))



    # Agent 3A: three-program shared-clock benchmark.
    agent3a_benchmark = evaluation.get("agent3a_benchmark")
    if isinstance(agent3a_benchmark, dict):
        story.append(PageBreak())
        _section(
            story,
            "05A  /  AGENT 3A THREE-PROGRAM BENCHMARK",
            "Student, brute-force and efficient implementations · shared wall-clock budget.",
            styles,
        )
        story.append(Paragraph(
            "All three programs are compiled before concurrent execution begins. "
            "The shared deadline applies to the benchmark as a whole; per-input "
            "execution limits are separate safety caps. These are single-run "
            "observations, not medians or complexity proofs.",
            styles["body_custom"],
        ))
        summary_rows = [["Program", "Status", "Cases run", "Successful", "Timed out / failed"]]
        batches = agent3a_benchmark.get("batches") or {}
        for program_key, label in (
            ("student", "Student"),
            ("brute_force", "Brute-force"),
            ("efficient", "Efficient"),
        ):
            batch = batches.get(program_key)
            if not isinstance(batch, dict):
                continue
            outcomes = batch.get("results") or []
            success_count = sum(
                1 for item in outcomes
                if isinstance(item, dict) and item.get("execution_class") == "program_success"
            )
            failure_count = sum(
                1 for item in outcomes
                if isinstance(item, dict) and item.get("execution_class") != "program_success"
            )
            summary_rows.append([
                label, batch.get("status", "unknown"), len(outcomes),
                success_count, failure_count,
            ])
        if len(summary_rows) > 1:
            story.append(_table(summary_rows, [35 * mm, 37 * mm, 27 * mm, 32 * mm, 35 * mm], styles))

        measured = agent3a_benchmark.get("chart_data") or []
        if isinstance(measured, list) and measured:
            runtime_chart = _multi_program_runtime_chart(
                "Measured runtime by actual input size",
                measured,
            )
            if runtime_chart is not None:
                story.append(Paragraph("Runtime observations by Input size (n).", styles["small"]))
                story.append(Spacer(1, 4 * mm))
                story.append(runtime_chart)
                story.append(Paragraph(
                    "Only successful measured runs are plotted. Timeouts and failed "
                    "executions remain in the benchmark outcome summary and are not "
                    "represented as zero runtime. These observations are not a Big-O proof.",
                    styles["small"],
                ))

        comparisons = agent3a_benchmark.get("differential_comparisons") or []
        generator_cases = ((evaluation.get("agent3a") or {}).get("generation") or {}).get("inputs", [])
        mismatches = []
        if isinstance(comparisons, list):
            for comparison in comparisons:
                if not isinstance(comparison, dict):
                    continue
                outcomes = comparison.get("outcomes") or {}
                student, brute = outcomes.get("student") or {}, outcomes.get("brute_force") or {}
                if student.get("execution_class") == "program_success" and brute.get("execution_class") == "program_success" and str(student.get("stdout", "")).strip() != str(brute.get("stdout", "")).strip():
                    case_number = comparison.get("case")
                    generated_input = comparison.get("input")
                    if not generated_input and isinstance(case_number, int) and isinstance(generator_cases, list) and 1 <= case_number <= len(generator_cases):
                        generated_input = (generator_cases[case_number - 1] or {}).get("input") if isinstance(generator_cases[case_number - 1], dict) else None
                    mismatches.append((comparison, student, brute, generated_input))
        if mismatches:
            story.append(Paragraph("Confirmed random-test disagreements (up to five)", styles["Heading2"]))
            failure_rows = [["Input size", "Input", "Brute-force output", "Student output"]]
            for comparison, student, brute, generated_input in mismatches[:5]:
                failure_rows.append([comparison.get("input_size", "-"), str(generated_input or "Unavailable")[:350], str(brute.get("stdout", ""))[:180], str(student.get("stdout", ""))[:180]])
            story.append(_table(failure_rows, [18 * mm, 72 * mm, 39 * mm, 39 * mm], styles))
        elif isinstance(comparisons, list) and comparisons:
            story.append(Paragraph(f"No confirmed student/brute-force output disagreements in {len(comparisons)} differential case(s). Inputs are omitted.", styles["small"]))

        if agent3a_benchmark.get("status"):
            story.append(Paragraph(
                "Overall benchmark status: " + _safe(agent3a_benchmark["status"]),
                styles["body_custom"],
            ))
        if agent3a_benchmark.get("limitations"):
            story.append(Paragraph(
                "Benchmark limitations: " + _safe(agent3a_benchmark["limitations"]),
                styles["body_custom"],
            ))

    # Agent 3B: validated AI-proposed edge cases and their actual executions.
    agent3b = evaluation.get("agent3b")
    agent3b_execution = evaluation.get("agent3b_execution")
    if isinstance(agent3b, dict) or isinstance(agent3b_execution, dict):
        _section(
            story,
            "05B  /  AGENT 3B EDGE-CASE ANALYSIS",
            "AI-proposed cases are schema-validated before execution.",
            styles,
        )
        proposed = agent3b.get("cases", []) if isinstance(agent3b, dict) else []
        if isinstance(agent3b, dict):
            story.append(Paragraph(
                f"Targeted edge cases: {len(proposed) if isinstance(proposed, list) else 0}. Inputs are shown only when an execution confirms a disagreement.",
                styles["body_custom"],
            ))
            validation = agent3b.get("validation")
            if isinstance(validation, dict):
                story.append(Paragraph(
                    f"Validated: {validation.get('validated_count', validation.get('valid_count', 'Not available'))}; "
                    f"rejected: {validation.get('rejected_count', 'Not available')}.",
                    styles["small"],
                ))

        if isinstance(agent3b_execution, dict):
            story.append(Paragraph(
                "Edge-case execution status: " +
                _safe(agent3b_execution.get("status", "unknown")),
                styles["body_custom"],
            ))
            execution_cases = (
                agent3b_execution.get("cases")
                or agent3b_execution.get("results")
                or agent3b_execution.get("differential_comparisons")
                or []
            )
            if isinstance(execution_cases, list) and execution_cases:
                mismatches = []
                for index, case in enumerate(execution_cases):
                    if not isinstance(case, dict):
                        continue
                    outcomes = case.get("outcomes") or {}
                    student, brute = outcomes.get("student") or {}, outcomes.get("brute_force") or {}
                    if student.get("execution_class") == "program_success" and brute.get("execution_class") == "program_success" and str(student.get("stdout", "")).strip() != str(brute.get("stdout", "")).strip():
                        case_name = proposed[index].get("name", f"case {index + 1}") if isinstance(proposed, list) and index < len(proposed) and isinstance(proposed[index], dict) else f"case {index + 1}"
                        mismatches.append((case_name, case, student, brute, outcomes.get("efficient") or {}))
                if mismatches:
                    story.append(Paragraph("Confirmed edge-case disagreements (up to five)", styles["Heading2"]))
                    execution_rows = [["Case", "Input", "Student", "Brute force", "Efficient"]]
                    for name, case, student, brute, efficient in mismatches[:5]:
                        execution_rows.append([name, str(case.get("input", ""))[:350], str(student.get("stdout", ""))[:180], str(brute.get("stdout", ""))[:180], str(efficient.get("stdout", ""))[:180]])
                    story.append(_table(execution_rows, [24 * mm, 62 * mm, 27 * mm, 27 * mm, 28 * mm], styles))
                else:
                    story.append(Paragraph(f"No confirmed student/brute-force output disagreements in {len(execution_cases)} edge case(s). Inputs are omitted.", styles["small"]))
            story.append(Paragraph(
                "Only confirmed student/brute-force output disagreements are listed above; "
                "timeouts and unavailable comparisons remain inconclusive.",
                styles["body_custom"],
            ))


    # 06 TEST GRAPHS
    _section(story, "06  /  TEST RESULT VISUALISATIONS", "Charts are shown only when measured test counts are available.", styles)
    if all(isinstance(x, (int, float)) and x >= 0 for x in (passed, failed, inconclusive)):
        story.append(_pie_chart(
            "Test outcome distribution",
            ["Passed", "Failed", "Inconclusive"],
            [passed, failed, inconclusive],
        ))
        story.append(Spacer(1, 8 * mm))
        story.append(_bar_chart(
            "Test outcome counts",
            ["Passed", "Failed", "Inconclusive"],
            [passed, failed, inconclusive],
        ))
        total = passed + failed + inconclusive
        if total:
            determinate = passed + failed
            story.append(Paragraph(
                f"<b>Observed pass rate:</b> {passed / determinate * 100:.1f}% "
                f"among determinate tests ({passed}/{determinate}). "
                f"<b>Coverage:</b> {total} tests, including {inconclusive} inconclusive.",
                styles["body_custom"],
            ))
    else:
        story.append(Paragraph(
            "No complete passed/failed/inconclusive count set was supplied. "
            "No test distribution chart can be responsibly generated.",
            styles["body_custom"],
        ))

    # 07 COMPLEXITY
    _section(story, "07  /  ALGORITHMIC COMPLEXITY", "Agent 4 · AI analysis, adaptive asymptotic curves, static signals and measured runtime are reported separately.", styles)
    agent4 = evaluation.get("complexity_analysis")
    if isinstance(agent4, dict):
        ai = agent4.get("ai_analysis") or {}
        story.append(Paragraph("Agent 4 analysis", styles["Heading2"]))
        agent4_rows = [["Analysis field", "Result"]]
        for label, value in (
            ("Algorithm", (ai.get("algorithm") or {}).get("name")),
            ("Input-size model", (ai.get("algorithm") or {}).get("input_size_model")),
            ("Best / average / worst time", " / ".join(str((ai.get("time_complexity") or {}).get(key) or "not distinguished") for key in ("best_case", "average_case", "worst_case"))),
            ("Auxiliary / total space", " / ".join(str((ai.get("space_complexity") or {}).get(key) or "unknown") for key in ("auxiliary", "total"))),
        ):
            if value is not None:
                agent4_rows.append([label, value])
        story.append(_table(agent4_rows, [55 * mm, 113 * mm], styles))
        for label, text in (
            ("Time derivation", (ai.get("time_complexity") or {}).get("derivation")),
            ("Space derivation", (ai.get("space_complexity") or {}).get("derivation")),
        ):
            if text:
                story.append(Paragraph(label, styles["Heading3"]))
                story.append(Paragraph(_safe(text), styles["body_custom"]))
        evidence = ai.get("evidence") or []
        if evidence:
            story.append(Paragraph("Source-linked reasoning", styles["Heading3"]))
            rows = [["Source lines", "Reasoning"]]
            for item in evidence[:6]:
                if isinstance(item, dict):
                    rows.append([
                        f"{item.get('line_start', '?')}-{item.get('line_end', '?')}",
                        item.get("claim", "-"),
                    ])
            story.append(_table(rows, [25 * mm, 143 * mm], styles))
        curves = agent4.get("complexity_graphs") or {}
        for key, graph in curves.items():
            chart = _complexity_curve_chart(graph, key.replace("_", " ").title())
            if chart is not None:
                story.append(chart)
            if isinstance(graph, dict):
                if graph.get("approximations"):
                    story.append(Paragraph(
                        "Numerical approximation: " + _safe(graph["approximations"]),
                        styles["small"],
                    ))
                if graph.get("warnings"):
                    story.append(Paragraph(
                        "Graph warning: " + _safe(graph["warnings"]),
                        styles["small"],
                    ))
        story.append(Paragraph(
            "Adaptive curves show the shape of the reported asymptotic expression. "
            "They are generic mathematical curves, not measured runtime or actual "
            "problem inputs. AI analysis remains advisory.",
            styles["body_custom"],
        ))
    elif agent4 is None:
        story.append(Paragraph("No Agent 4 complexity analysis was supplied.", styles["body_custom"]))
    if isinstance(complexity, dict) and complexity:
        estimate_rows = [["Static source estimate", "Reported growth"]]
        for label, key in (("Time", "time_complexity"), ("Space", "space_complexity")):
            if complexity.get(key):
                estimate_rows.append([label, complexity[key]])
        if len(estimate_rows) > 1:
            story.append(_table(estimate_rows, [42 * mm, 126 * mm], styles))
            story.append(Paragraph(
                "Static estimates are heuristic signals from source patterns, not measured runtimes or proof.",
                styles["small"],
            ))

    # Empirical benchmark evidence is deliberately separate from static estimates.
    benchmark = evaluation.get("complexity_benchmark")
    if isinstance(benchmark, dict):
        story.append(Paragraph(
            "Empirical runtime benchmark", styles["Heading2"]
        ))
        story.append(Paragraph(
            "These measurements are observations for explicitly supplied inputs. "
            "They are not a Big-O proof and do not establish correctness.",
            styles["body_custom"],
        ))

        benchmark_rows = [[
            "Input size", "Successful", "Failed",
            "Median (s)", "Minimum (s)", "Maximum (s)",
        ]]
        benchmark_results = benchmark.get("results")
        if isinstance(benchmark_results, list):
            for item in benchmark_results[:100]:
                if not isinstance(item, dict):
                    continue
                benchmark_rows.append([
                    item.get("input_size", "-"),
                    item.get("successful_runs", "-"),
                    item.get("failed_runs", "-"),
                    (
                        f'{item["median_runtime_seconds"]:.6f}'
                        if isinstance(item.get("median_runtime_seconds"), (int, float))
                        and not isinstance(item.get("median_runtime_seconds"), bool)
                        else "-"
                    ),
                    (
                        f'{item["minimum_runtime_seconds"]:.6f}'
                        if isinstance(item.get("minimum_runtime_seconds"), (int, float))
                        and not isinstance(item.get("minimum_runtime_seconds"), bool)
                        else "-"
                    ),
                    (
                        f'{item["maximum_runtime_seconds"]:.6f}'
                        if isinstance(item.get("maximum_runtime_seconds"), (int, float))
                        and not isinstance(item.get("maximum_runtime_seconds"), bool)
                        else "-"
                    ),
                ])
        if len(benchmark_rows) > 1:
            story.append(_table(
                benchmark_rows,
                [22 * mm, 25 * mm, 20 * mm, 31 * mm, 31 * mm, 31 * mm],
                styles,
            ))

        chart_data = benchmark.get("chart_data")
        valid_points = []
        if isinstance(chart_data, list):
            for item in chart_data:
                if not isinstance(item, dict):
                    continue
                x = item.get("input_size")
                y = item.get("median_runtime_seconds")
                if (
                    isinstance(x, (int, float))
                    and not isinstance(x, bool)
                    and isinstance(y, (int, float))
                    and not isinstance(y, bool)
                    and math.isfinite(x)
                    and math.isfinite(y)
                    and x > 0
                    and y >= 0
                ):
                    valid_points.append((float(x), float(y)))

        valid_points.sort(key=lambda point: point[0])
        if len(valid_points) >= 2:
            story.append(_line_chart(
                "Median elapsed runtime vs. supplied input size",
                valid_points,
            ))
        elif valid_points:
            story.append(Paragraph(
                "Only one valid input-size measurement is available; "
                "a runtime growth chart requires at least two distinct sizes.",
                styles["body_custom"],
            ))
        else:
            story.append(Paragraph(
                "No valid successful benchmark measurements were supplied; "
                "no runtime chart was generated.",
                styles["body_custom"],
            ))

        # Internal runner settings and setup measurements do not help the
        # student interpret runtime; retain the table and measured curve only.

    # Agent 4 and benchmark notes above distinguish estimates from measurements.

    # 08 QUALITY
    _section(story, "08  /  CODE QUALITY ANALYSIS", "Agent 6 · Maintainability and safety-pattern indicators.", styles)
    if isinstance(quality, dict) and quality:
        quality_rows = [["Quality field", "Reported value"]]
        for label, key in (
            ("Analysis status", "status"),
            ("Heuristic score", "score"),
            ("Score type", "score_type"),
            ("Finding count", "finding_count"),
        ):
            value = quality.get(key)
            if value is not None:
                quality_rows.append([label, value])
        if len(quality_rows) > 1:
            story.append(_table(quality_rows, [65 * mm, 103 * mm], styles))

        rubric_ratings = quality.get("rubric_ratings")
        if isinstance(rubric_ratings, dict) and rubric_ratings:
            story.append(Paragraph("Fixed-anchor Agent 6 rubric", styles["Heading2"]))
            rubric_rows = [["Dimension", "Score", "Evidence-based rationale"]]
            for name in ("readability", "modularity", "design_originality"):
                item = rubric_ratings.get(name)
                if not isinstance(item, dict):
                    continue
                rating = item.get("rating")
                score = f"{rating * 25} / 100" if isinstance(rating, int) and not isinstance(rating, bool) and 0 <= rating <= 4 else "Unavailable"
                evidence = item.get("evidence", [])
                citation = "; ".join(
                    f"line {ref.get('line')}: {ref.get('quote')}"
                    for ref in evidence if isinstance(ref, dict)
                ) if isinstance(evidence, list) else ""
                rationale = str(item.get("rationale", ""))
                if citation:
                    rationale += " Source: " + citation
                rubric_rows.append([name.replace("_", " ").title(), score, rationale])
            if len(rubric_rows) > 1:
                story.append(_table(rubric_rows, [40 * mm, 26 * mm, 102 * mm], styles))

        findings = _flatten_items(quality)
        if findings:
            story.append(Paragraph("Actionable review notes", styles["Heading2"]))
            finding_rows = [["Priority", "Finding"]]
            severities = {"high": 0, "medium": 0, "low": 0}
            for item in findings[:5]:
                if isinstance(item, dict):
                    severity = str(item.get("severity", "unspecified")).lower()
                    if severity in severities:
                        severities[severity] += 1
                    finding_rows.append([
                        severity,
                        item.get("message", "-"),
                    ])
            if len(finding_rows) > 1:
                story.append(_table(
                    finding_rows,
                    [32 * mm, 136 * mm],
                    styles,
                ))
    else:
        story.append(Paragraph(
            "No code-quality analysis was attached to this evaluation.",
            styles["body_custom"],
        ))
    story.append(Paragraph(
        "Code-review scores describe the submitted code's structure and readability; "
        "they are separate from correctness evidence.", styles["small"],
    ))


    # 09 MATHEMATICAL VERIFICATION
    _section(story, "09  /  MATHEMATICAL VERIFICATION", "Agent 5 · AI-led mathematical correctness analysis.", styles)

    if isinstance(verification, dict) and verification:
        for heading, key in (
            ("Theorem", "theorem"),
            ("Proof strategy", "proof_strategy"),
        ):
            value = verification.get(key)
            if value:
                story.append(Paragraph(heading, styles["Heading2"]))
                if isinstance(value, list):
                    for index, item in enumerate(value, 1):
                        story.append(Paragraph(
                            f"{index}. {_safe(item)}", styles["body_custom"]
                        ))
                else:
                    story.append(Paragraph(_safe(value), styles["body_custom"]))

        proof_steps = verification.get("proof_steps", [])
        if proof_steps:
            story.append(Paragraph("Mathematical proof steps", styles["Heading2"]))
            for index, step in enumerate(proof_steps, 1):
                if not isinstance(step, dict):
                    continue
                story.append(Paragraph(
                    f"<b>Step {index}.</b> {_safe(step.get('claim', ''))}",
                    styles["body_custom"],
                ))
                if step.get("equation"):
                    story.append(Paragraph(
                        f"<b>Equation:</b> {_safe(step['equation'])}",
                        styles["body_custom"],
                    ))
                if step.get("justification"):
                    story.append(Paragraph(
                        f"<b>Justification:</b> {_safe(step['justification'])}",
                        styles["body_custom"],
                    ))

        conclusion = verification.get("conclusion")
        if conclusion:
            story.append(Paragraph("Conclusion", styles["Heading2"]))
            story.append(Paragraph(_safe(conclusion), styles["body_custom"]))

        counterexample = verification.get("counterexample")
        if isinstance(counterexample, dict):
            story.append(Paragraph("Potential counterexample", styles["Heading2"]))
            rows = [["Element", "Details"]]
            for key in (
                "input", "expected_behavior",
                "observed_or_predicted_behavior", "explanation"
            ):
                if counterexample.get(key) is not None:
                    rows.append([
                        key.replace("_", " ").title(),
                        _safe(counterexample[key]),
                    ])
            story.append(_table(rows, [55 * mm, 113 * mm], styles))
        story.append(Paragraph(
            "AI-generated proof sketch; not machine-checked.", styles["small"],
        ))
    else:
        story.append(Paragraph(
            "No mathematical-verification result was supplied. "
            "No proof status can be inferred.",
            styles["body_custom"],
        ))

    # 10 GRADING
    _section(story, "10  /  GRADING & SCORING", "Deterministic score and eligibility evidence.", styles)
    if isinstance(grading, dict):
        grade_rows = [["Grading field", "Reported value"]]
        for label, key in (
            ("Overall score", "score"),
            ("Message", "message"),
        ):
            value = grading.get(key)
            if value is not None:
                grade_rows.append([label, value])
        if len(grade_rows) > 1:
            story.append(_table(grade_rows, [65 * mm, 103 * mm], styles))

        breakdown = grading.get("breakdown")
        if isinstance(breakdown, dict) and breakdown:
            story.append(Paragraph("Weighted grading breakdown", styles["Heading2"]))
            breakdown_rows = [["Metric", "Weight", "Score", "Rationale"]]
            chart_labels, chart_values = [], []
            for key, item in breakdown.items():
                if not isinstance(item, dict):
                    continue
                status = item.get("status", "unspecified")
                score = item.get("score")
                breakdown_rows.append([
                    key.replace("_", " ").title(),
                    item.get("weight", "-"),
                    "Unavailable" if score is None else score,
                    item.get("reason", "-"),
                ])
                if (
                    status == "included"
                    and isinstance(score, (int, float))
                    and not isinstance(score, bool)
                ):
                    chart_labels.append(key.replace("_", " ").title())
                    chart_values.append(float(score))
            story.append(_table(
                breakdown_rows,
                [35 * mm, 22 * mm, 22 * mm, 85 * mm],
                styles,
            ))
            if chart_labels:
                story.append(_bar_chart(
                    "Scores for included grading metrics",
                    chart_labels,
                    chart_values,
                ))

        excluded = grading.get("excluded_metrics")
        if excluded:
            story.append(Paragraph("Excluded metrics", styles["Heading2"]))
            story.append(Paragraph(_safe(excluded), styles["body_custom"]))
        provenance = grading.get("reproducibility")
    else:
        story.append(Paragraph("No grading result was supplied.", styles["body_custom"]))

    story.append(Paragraph(
        "Unavailable evidence is excluded; the remaining metric weights are renormalized.",
        styles["small"],
    ))


    # The final page is intentionally a concise, graphic scorecard for sharing.
    story += [
        PageBreak(),
        Paragraph("FINAL GRADE / REPRODUCIBLE SCORECARD", styles["section"]),
        Paragraph(
            "One weighted result, with every component and its evidence availability shown.",
            styles["subtitle"],
        ),
        HRFlowable(width="100%", thickness=1, color=BLUE, spaceAfter=14),
        _final_grade_graph(grading if isinstance(grading, dict) else {}),
        Spacer(1, 7 * mm),
    ]
    breakdown = grading.get("breakdown", {}) if isinstance(grading, dict) else {}
    included = sum(1 for item in breakdown.values() if isinstance(item, dict) and item.get("status") == "included")
    unavailable = sum(1 for item in breakdown.values() if isinstance(item, dict) and item.get("status") != "included")
    story.append(Paragraph(
        f"<b>Evidence:</b> {included} metrics included; {unavailable} unavailable or excluded. "
        "Determinate test outcomes contribute to empirical rates; timeouts and infrastructure failures remain inconclusive. "
        "The mathematical score reflects the AI verifier's proof-sketch or counterexample outcome, not machine-checked proof.",
        styles["body_custom"],
    ))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "<b>Rubric:</b> correctness 45% · edge cases 15% · mathematical analysis 15% · "
        "complexity fit 10% · readability 5% · modularity 5% · design originality 5%. "
        "Unavailable metrics are excluded and remaining weights are renormalized. AI ratings use fixed 0-4 anchors, mapped to 0-100.",
        styles["small"],
    ))
    provenance = grading.get("reproducibility", {}) if isinstance(grading, dict) else {}
    if provenance:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(
            "<b>Reproducibility ID:</b> " + escape(str(provenance.get("fingerprint", "Unavailable"))) + "<br/>"
            "<b>Rules:</b> " + escape(str(provenance.get("rules_version", "Unavailable"))) + "<br/>"
            "<b>Grade snapshot:</b> " + escape({"saved": "First complete grade saved", "reused": "Matching grade reused"}.get(str(provenance.get("grade_snapshot_status")), "Not yet saved")),
            styles["small"],
        ))
    story += [
        Spacer(1, 6 * mm),
        HRFlowable(width="100%", thickness=1, color=BLUE, spaceAfter=8),
        Paragraph(
            "<b>END OF REPORT</b> · Evidence-derived report; no missing measurements or proof claims are fabricated.",
            styles["small"],
        ),
    ]

    doc.build(story, onFirstPage=_draw_page, onLaterPages=_draw_page)
    return destination
