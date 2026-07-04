"""
Advanced Exporter for Smart Inhaler
Includes Charts + Hospital Style + AI Summary
"""

import pandas as pd
from io import BytesIO
from datetime import datetime
from typing import Dict, Optional

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

import matplotlib.pyplot as plt


# =========================
# CLASS
# =========================
class DataExporter:

    def __init__(self):
        self.styles = getSampleStyleSheet()

        # Custom styles
        if "CustomTitle" not in self.styles:
            self.styles.add(ParagraphStyle(
                name='CustomTitle',
                parent=self.styles['Heading1'],
                alignment=1,
                fontSize=20,
                textColor=colors.darkblue
            ))

        if "CustomBody" not in self.styles:
            self.styles.add(ParagraphStyle(
                name='CustomBody',
                parent=self.styles['Normal'],
                fontSize=11,
                spaceAfter=6
            ))

    # =========================
    # PDF REPORT
    # =========================
    def generate_pdf_report(self, patient: Dict, df: pd.DataFrame) -> bytes:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)

        elements = []

        # =========================
        # TITLE (Hospital Style)
        # =========================
        elements.append(Paragraph(
            "🏥 SMART INHALER MEDICAL REPORT",
            self.styles["CustomTitle"]
        ))
        elements.append(Spacer(1, 12))

        elements.append(Paragraph(
            f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            self.styles["CustomBody"]
        ))
        elements.append(Spacer(1, 12))

        # =========================
        # PATIENT INFO
        # =========================
        elements.append(Paragraph("Patient Information", self.styles["Heading2"]))

        patient_table = Table([
            ["Name", patient.get("name")],
            ["Age", patient.get("age")],
            ["Severity", patient.get("asthma_severity")],
            ["Doctor", patient.get("doctor_contact")]
        ])

        patient_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("BACKGROUND", (0, 0), (0, -1), colors.lightblue)
        ]))

        elements.append(patient_table)
        elements.append(Spacer(1, 20))

        # =========================
        # SUMMARY
        # =========================
        elements.append(Paragraph("Usage Summary", self.styles["Heading2"]))

        total = len(df)
        avg_flow = df["flow_rate"].mean() if not df.empty else 0
        avg_gas = df["gas"].mean() if not df.empty else 0

        summary_table = Table([
            ["Total Uses", total],
            ["Avg Flow Rate", f"{avg_flow:.2f}"],
            ["Avg Gas Level", f"{avg_gas:.2f}"]
        ])

        summary_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 1, colors.black)
        ]))

        elements.append(summary_table)
        elements.append(Spacer(1, 20))

        # =========================
        # 📊 CHART 1: FLOW TREND
        # =========================
        if not df.empty:
            fig, ax = plt.subplots()
            df_sorted = df.sort_values("timestamp")
            ax.plot(df_sorted["timestamp"], df_sorted["flow_rate"])
            ax.set_title("Flow Rate Trend")

            chart_buffer = BytesIO()
            plt.savefig(chart_buffer, format='png')
            plt.close()

            chart_buffer.seek(0)

            elements.append(Paragraph("Flow Rate Trend", self.styles["Heading2"]))
            elements.append(Image(chart_buffer, width=400, height=200))
            elements.append(Spacer(1, 20))

        # =========================
        # 📊 CHART 2: QUALITY PIE
        # =========================
        if not df.empty:
            quality_counts = df["quality"].value_counts()

            fig, ax = plt.subplots()
            ax.pie(quality_counts, labels=quality_counts.index, autopct="%1.1f%%")
            ax.set_title("Usage Quality")

            pie_buffer = BytesIO()
            plt.savefig(pie_buffer, format='png')
            plt.close()

            pie_buffer.seek(0)

            elements.append(Paragraph("Usage Quality Distribution", self.styles["Heading2"]))
            elements.append(Image(pie_buffer, width=300, height=300))
            elements.append(Spacer(1, 20))

        # =========================
        # 🤖 AI SUMMARY
        # =========================
        elements.append(Paragraph("AI Health Insights", self.styles["Heading2"]))

        if not df.empty:
            issues = []

            if avg_gas > 100:
                issues.append("High gas exposure detected")
            if avg_flow < 30:
                issues.append("Low inhalation flow rate")
            if df["motion"].mean() > 2:
                issues.append("Improper inhaler usage pattern")

            if not issues:
                ai_text = "Patient condition appears stable."
            else:
                ai_text = " | ".join(issues)

        else:
            ai_text = "No data available."

        elements.append(Paragraph(ai_text, self.styles["CustomBody"]))
        elements.append(Spacer(1, 20))

        # =========================
        # RECENT TABLE
        # =========================
        elements.append(Paragraph("Recent Records", self.styles["Heading2"]))

        table_data = [["Time", "Flow", "Gas", "Quality"]]

        for _, row in df.head(10).iterrows():
            table_data.append([
                str(row["timestamp"])[:19],
                f"{row['flow_rate']:.1f}",
                f"{row['gas']:.1f}",
                row["quality"]
            ])

        table = Table(table_data)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 1, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)
        ]))

        elements.append(table)

        # =========================
        # BUILD PDF
        # =========================
        doc.build(elements)
        buffer.seek(0)

        return buffer.getvalue()


# =========================
# SHORTCUT
# =========================
def generate_patient_report(patient, df):
    exporter = DataExporter()
    return exporter.generate_pdf_report(patient, df)