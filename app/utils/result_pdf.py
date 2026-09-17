"""Generates a student's termly result slip as a downloadable PDF.

Kept deliberately dependency-light (reportlab only, no system libraries)
so it works on constrained hosts like Render's free tier.
"""
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

INK = colors.HexColor("#16233F")
GOLD = colors.HexColor("#C99A2E")
CHALK = colors.HexColor("#1F4D3E")
SLATE = colors.HexColor("#5B6472")
BORDER = colors.HexColor("#E2E6E4")


def build_result_pdf(student, term, results, average, school_name="[Your School Name]", photo_full_path=None):
    """Returns a BytesIO containing the rendered PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=18 * mm, rightMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("SchoolTitle", parent=styles["Heading1"], fontSize=18, textColor=INK, alignment=TA_CENTER, spaceAfter=2)
    sub_style = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=10, textColor=SLATE, alignment=TA_CENTER, spaceAfter=0)
    label_style = ParagraphStyle("Label", parent=styles["Normal"], fontSize=9, textColor=SLATE)
    value_style = ParagraphStyle("Value", parent=styles["Normal"], fontSize=11, textColor=INK)
    remark_style = ParagraphStyle("Remark", parent=styles["Normal"], fontSize=10, textColor=INK, alignment=TA_RIGHT)

    elements = []

    elements.append(Paragraph(school_name, title_style))
    elements.append(Paragraph("Student Termly Result Slip", sub_style))
    elements.append(Spacer(1, 4 * mm))
    elements.append(HRFlowable(width="100%", thickness=1.4, color=GOLD))
    elements.append(Spacer(1, 6 * mm))

    # ---- student info block (with photo if available) ----
    info_rows = [
        [Paragraph("Student", label_style), Paragraph(student.full_name, value_style)],
        [Paragraph("Admission No.", label_style), Paragraph(student.admission_number, value_style)],
        [Paragraph("Class", label_style), Paragraph(student.class_arm.display_name if student.class_arm else "—", value_style)],
        [Paragraph("Term", label_style), Paragraph(f"{term.name} — {term.session.name}", value_style)],
    ]
    info_table = Table(info_rows, colWidths=[35 * mm, 90 * mm])
    info_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    if photo_full_path:
        try:
            photo = Image(photo_full_path, width=28 * mm, height=28 * mm)
            header_table = Table([[info_table, photo]], colWidths=[125 * mm, 30 * mm])
            header_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
            elements.append(header_table)
        except Exception:
            elements.append(info_table)
    else:
        elements.append(info_table)

    elements.append(Spacer(1, 6 * mm))

    # ---- results table ----
    header = ["Subject", "CA", "Exam", "Total", "Grade"]
    data = [header]
    for r in results:
        data.append([
            r.class_subject.subject.name,
            str(r.ca_score),
            str(r.exam_score),
            str(r.total_score),
            r.grade or "—",
        ])

    table = Table(data, colWidths=[70 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.6, BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6F5")]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 6 * mm))

    if average is not None:
        elements.append(Paragraph(f"<b>Term Average: {average}</b>", remark_style))
        elements.append(Spacer(1, 10 * mm))

    elements.append(HRFlowable(width="100%", thickness=0.6, color=BORDER))
    elements.append(Spacer(1, 3 * mm))
    footer_style = ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8, textColor=SLATE, alignment=TA_CENTER)
    elements.append(Paragraph("This is a system-generated result slip and does not require a signature.", footer_style))

    doc.build(elements)
    buf.seek(0)
    return buf
