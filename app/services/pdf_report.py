from __future__ import annotations

from datetime import datetime
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


class NumberedCanvas(canvas.Canvas):
    """
    Canvas personalizado para calcular y mostrar el número total de páginas 
    ("Página X de Y") y agregar encabezados/pies de página ejecutivos.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count: int):
        self.saveState()
        width, height = letter

        # Encabezado corporativo (a partir de página 2 o en todas)
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#64748b"))
        self.drawString(36, height - 30, "REPORTE EJECUTIVO - CONSUMO DE HORAS")

        self.setFont("Helvetica", 8)
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        self.drawRightString(width - 36, height - 30, f"Generado el: {now_str}")

        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.5)
        self.line(36, height - 35, width - 36, height - 35)

        # Pie de página
        self.line(36, 40, width - 36, 40)
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))
        self.drawString(36, 25, "Confidencial - Reporte Interno de Consumo de Horas Jira")
        page_str = f"Página {self._pageNumber} de {page_count}"
        self.drawRightString(width - 36, 25, page_str)

        self.restoreState()


def generate_hours_consumption_pdf(
    report_data: dict,
    client_filter_label: str = "Todos los clientes",
    agent_filter_label: str = "Todos los agentes",
    status_filter_label: str = "Todos los estados",
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=48,
        bottomMargin=54,
    )

    styles = getSampleStyleSheet()

    # Normal Styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0f172a"),
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#0ea5e9"),
    )
    meta_label_style = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#334155"),
    )
    meta_val_style = ParagraphStyle(
        "MetaVal",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#0f172a"),
    )
    section_heading = ParagraphStyle(
        "SectionHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=6,
    )
    cell_head = ParagraphStyle(
        "CellHead",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=colors.white,
    )
    cell_head_right = ParagraphStyle(
        "CellHeadRight",
        parent=cell_head,
        alignment=2,  # Right
    )
    cell_body = ParagraphStyle(
        "CellBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#1e293b"),
    )
    cell_body_bold = ParagraphStyle(
        "CellBodyBold",
        parent=cell_body,
        fontName="Helvetica-Bold",
    )
    cell_body_right = ParagraphStyle(
        "CellBodyRight",
        parent=cell_body,
        alignment=2,
    )
    cell_body_right_bold = ParagraphStyle(
        "CellBodyRightBold",
        parent=cell_body_right,
        fontName="Helvetica-Bold",
    )

    story = []

    # Title & Header Banner
    story.append(Paragraph("REPORTE EJECUTIVO DE CONSUMO DE HORAS", title_style))
    story.append(Paragraph("Resumen Estratégico e Indicadores de Gestión de Servicio", subtitle_style))
    story.append(Spacer(1, 14))

    # Metadata Panel Table
    start_d = report_data.get("start_date", "")
    end_d = report_data.get("end_date", "")
    meta_data = [
        [
            Paragraph("Período de Análisis:", meta_label_style),
            Paragraph(f"{start_d} al {end_d}", meta_val_style),
            Paragraph("Cliente:", meta_label_style),
            Paragraph(client_filter_label, meta_val_style),
        ],
        [
            Paragraph("Técnico / Agente:", meta_label_style),
            Paragraph(agent_filter_label, meta_val_style),
            Paragraph("Estados Filtrados:", meta_label_style),
            Paragraph(status_filter_label, meta_val_style),
        ],
        [
            Paragraph("Fecha de Emisión:", meta_label_style),
            Paragraph(datetime.now().strftime("%Y-%m-%d %H:%M"), meta_val_style),
            Paragraph("", meta_label_style),
            Paragraph("", meta_val_style),
        ],
    ]
    meta_table = Table(meta_data, colWidths=[110, 160, 100, 170])
    meta_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#f1f5f9")),
                ("PADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(meta_table)
    story.append(Spacer(1, 16))

    # KPI Summary Cards Table
    kpis = report_data.get("kpis", {})
    tot_hrs = kpis.get("total_hours", 0.0)
    tot_tkts = kpis.get("total_tickets", 0)
    avg_hrs = kpis.get("avg_hours_per_ticket", 0.0)
    top_c_name = kpis.get("top_client_name") or "N/A"
    top_c_hrs = kpis.get("top_client_hours", 0.0)

    kpi_card_style_num = ParagraphStyle(
        "KpiNum",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=18,
        textColor=colors.HexColor("#0ea5e9"),
        alignment=1,  # Center
    )
    kpi_card_style_lbl = ParagraphStyle(
        "KpiLbl",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#64748b"),
        alignment=1,
    )

    kpi_data = [
        [
            Paragraph(f"{tot_hrs:.1f} hrs", kpi_card_style_num),
            Paragraph(f"{tot_tkts}", kpi_card_style_num),
            Paragraph(f"{avg_hrs:.2f} hrs", kpi_card_style_num),
            Paragraph(f"{top_c_name[:18]}", kpi_card_style_num),
        ],
        [
            Paragraph("TOTAL CONSUMIDO", kpi_card_style_lbl),
            Paragraph("TICKETS TRABAJADOS", kpi_card_style_lbl),
            Paragraph("PROMEDIO / TICKET", kpi_card_style_lbl),
            Paragraph(f"MAYOR CONSUMO ({top_c_hrs:.1f}h)", kpi_card_style_lbl),
        ],
    ]
    kpi_table = Table(kpi_data, colWidths=[135, 135, 135, 135])
    kpi_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0f172a")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#1e293b")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#334155")),
                ("PADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(kpi_table)
    story.append(Spacer(1, 20))

    # Section 1: Resumen por Cliente
    clients = report_data.get("clients", [])
    if clients:
        story.append(Paragraph("1. Consumo de Horas por Cliente", section_heading))
        client_table_data = [
            [
                Paragraph("Cliente", cell_head),
                Paragraph("Tickets", cell_head_right),
                Paragraph("Horas Registradas", cell_head_right),
                Paragraph("% del Total", cell_head_right),
            ]
        ]
        for c_row in clients[:15]:  # Top 15 clientes
            client_table_data.append(
                [
                    Paragraph(c_row["client_name"], cell_body_bold),
                    Paragraph(str(c_row["ticket_count"]), cell_body_right),
                    Paragraph(f"{c_row['hours_logged']:.2f} hrs", cell_body_right_bold),
                    Paragraph(f"{c_row['percentage']:.1f}%", cell_body_right),
                ]
            )

        client_table = Table(client_table_data, colWidths=[240, 80, 110, 110])
        client_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("PADDING", (0, 0), (-1, -1), 5),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ]
            )
        )
        story.append(client_table)
        story.append(Spacer(1, 18))

    # Section 2: Resumen por Agente / Técnico
    agents = report_data.get("agents", [])
    if agents:
        story.append(Paragraph("2. Consumo de Horas por Agente / Técnico", section_heading))
        agent_table_data = [
            [
                Paragraph("Agente / Técnico", cell_head),
                Paragraph("Tickets Atendidos", cell_head_right),
                Paragraph("Horas Registradas", cell_head_right),
                Paragraph("% del Total", cell_head_right),
            ]
        ]
        for a_row in agents:
            agent_table_data.append(
                [
                    Paragraph(a_row["agent_name"], cell_body_bold),
                    Paragraph(str(a_row["ticket_count"]), cell_body_right),
                    Paragraph(f"{a_row['hours_logged']:.2f} hrs", cell_body_right_bold),
                    Paragraph(f"{a_row['percentage']:.1f}%", cell_body_right),
                ]
            )

        agent_table = Table(agent_table_data, colWidths=[240, 80, 110, 110])
        agent_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("PADDING", (0, 0), (-1, -1), 5),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ]
            )
        )
        story.append(agent_table)
        story.append(Spacer(1, 18))

    # Section 3: Resumen por Nivel de Servicio
    service_levels = report_data.get("service_levels", [])
    if service_levels:
        story.append(Paragraph("3. Consumo por Nivel de Servicio", section_heading))
        sl_table_data = [
            [
                Paragraph("Nivel de Servicio", cell_head),
                Paragraph("Tickets", cell_head_right),
                Paragraph("Horas Registradas", cell_head_right),
                Paragraph("% del Total", cell_head_right),
            ]
        ]
        for sl_row in service_levels:
            sl_table_data.append(
                [
                    Paragraph(sl_row["service_level"], cell_body_bold),
                    Paragraph(str(sl_row["ticket_count"]), cell_body_right),
                    Paragraph(f"{sl_row['hours_logged']:.2f} hrs", cell_body_right_bold),
                    Paragraph(f"{sl_row['percentage']:.1f}%", cell_body_right),
                ]
            )

        sl_table = Table(sl_table_data, colWidths=[240, 80, 110, 110])
        sl_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("PADDING", (0, 0), (-1, -1), 5),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ]
            )
        )
        story.append(sl_table)
        story.append(Spacer(1, 18))

    # Section 4: Resumen por Estado de Ticket
    statuses = report_data.get("statuses", [])
    if statuses:
        story.append(Paragraph("4. Consumo por Estado de Ticket", section_heading))
        st_table_data = [
            [
                Paragraph("Estado de Ticket", cell_head),
                Paragraph("Tickets", cell_head_right),
                Paragraph("Horas Registradas", cell_head_right),
                Paragraph("% del Total", cell_head_right),
            ]
        ]
        for st_row in statuses:
            st_table_data.append(
                [
                    Paragraph(st_row["status_name"], cell_body_bold),
                    Paragraph(str(st_row["ticket_count"]), cell_body_right),
                    Paragraph(f"{st_row['hours_logged']:.2f} hrs", cell_body_right_bold),
                    Paragraph(f"{st_row['percentage']:.1f}%", cell_body_right),
                ]
            )

        st_table = Table(st_table_data, colWidths=[240, 80, 110, 110])
        st_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("PADDING", (0, 0), (-1, -1), 5),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ]
            )
        )
        story.append(st_table)
        story.append(Spacer(1, 18))

    # Section 5: Detalle de Tickets Atendidos
    tickets = report_data.get("tickets", [])
    if tickets:
        story.append(Paragraph("5. Detalle de Tickets con Registros de Horas", section_heading))
        tkt_table_data = [
            [
                Paragraph("Clave Jira", cell_head),
                Paragraph("Resumen / Descripción", cell_head),
                Paragraph("Cliente", cell_head),
                Paragraph("Técnico", cell_head),
                Paragraph("Horas", cell_head_right),
            ]
        ]
        for t_row in tickets[:50]:  # Top 50 tickets por consumo
            summary_trunc = t_row["summary"]
            if len(summary_trunc) > 42:
                summary_trunc = summary_trunc[:40] + "..."
            tkt_table_data.append(
                [
                    Paragraph(t_row["jira_key"], cell_body_bold),
                    Paragraph(summary_trunc, cell_body),
                    Paragraph(t_row["client_name"], cell_body),
                    Paragraph(t_row["agent_name"], cell_body),
                    Paragraph(f"{t_row['hours_logged']:.2f} h", cell_body_right_bold),
                ]
            )

        tkt_table = Table(tkt_table_data, colWidths=[65, 195, 120, 100, 60])
        tkt_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("PADDING", (0, 0), (-1, -1), 4),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ]
            )
        )
        story.append(tkt_table)

    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer.getvalue()


def generate_visits_report_pdf(
    report_data: dict,
    client_filter_label: str = "Todos los clientes",
    agent_filter_label: str = "Todos los agentes",
    visit_type_filter_label: str = "Todas las visitas",
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=48,
        bottomMargin=54,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0f172a"),
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#0ea5e9"),
    )
    meta_label_style = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#334155"),
    )
    meta_val_style = ParagraphStyle(
        "MetaVal",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#0f172a"),
    )
    section_heading = ParagraphStyle(
        "SectionHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=6,
    )
    cell_head = ParagraphStyle(
        "CellHead",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=colors.white,
    )
    cell_head_right = ParagraphStyle(
        "CellHeadRight",
        parent=cell_head,
        alignment=2,
    )
    cell_body = ParagraphStyle(
        "CellBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#1e293b"),
    )
    cell_body_bold = ParagraphStyle(
        "CellBodyBold",
        parent=cell_body,
        fontName="Helvetica-Bold",
    )
    cell_body_right = ParagraphStyle(
        "CellBodyRight",
        parent=cell_body,
        alignment=2,
    )
    cell_body_right_bold = ParagraphStyle(
        "CellBodyRightBold",
        parent=cell_body_right,
        fontName="Helvetica-Bold",
    )

    story = []

    # Title & Subtitle
    story.append(Paragraph("REPORTE EJECUTIVO DE VISITAS REALIZADAS", title_style))
    story.append(Paragraph("Resumen de Visitas Programadas y No Programadas", subtitle_style))
    story.append(Spacer(1, 14))

    # Metadata Panel
    start_d = report_data.get("start_date", "")
    end_d = report_data.get("end_date", "")
    meta_data = [
        [
            Paragraph("Período de Análisis:", meta_label_style),
            Paragraph(f"{start_d} al {end_d}", meta_val_style),
            Paragraph("Cliente:", meta_label_style),
            Paragraph(client_filter_label, meta_val_style),
        ],
        [
            Paragraph("Técnico / Agente:", meta_label_style),
            Paragraph(agent_filter_label, meta_val_style),
            Paragraph("Tipo de Visita:", meta_label_style),
            Paragraph(visit_type_filter_label, meta_val_style),
        ],
        [
            Paragraph("Fecha de Emisión:", meta_label_style),
            Paragraph(datetime.now().strftime("%Y-%m-%d %H:%M"), meta_val_style),
            Paragraph("", meta_label_style),
            Paragraph("", meta_val_style),
        ],
    ]
    meta_table = Table(meta_data, colWidths=[110, 160, 100, 170])
    meta_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#f1f5f9")),
                ("PADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(meta_table)
    story.append(Spacer(1, 16))

    # KPI Summary Cards
    kpis = report_data.get("kpis", {})
    tot_visits = kpis.get("total_visits", 0)
    sch_visits = kpis.get("scheduled_visits", 0)
    unsch_visits = kpis.get("unscheduled_visits", 0)
    tot_hrs = kpis.get("total_hours", 0.0)

    kpi_card_style_num = ParagraphStyle(
        "KpiNum",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=18,
        textColor=colors.HexColor("#0ea5e9"),
        alignment=1,
    )
    kpi_card_style_lbl = ParagraphStyle(
        "KpiLbl",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#64748b"),
        alignment=1,
    )

    kpi_table_data = [
        [
            Paragraph(str(tot_visits), kpi_card_style_num),
            Paragraph(str(sch_visits), kpi_card_style_num),
            Paragraph(str(unsch_visits), kpi_card_style_num),
            Paragraph(f"{tot_hrs:.1f} hrs", kpi_card_style_num),
        ],
        [
            Paragraph("TOTAL VISITAS", kpi_card_style_lbl),
            Paragraph("VISITAS PROGRAMADAS", kpi_card_style_lbl),
            Paragraph("VISITAS NO PROGRAMADAS", kpi_card_style_lbl),
            Paragraph("HORAS REGISTRADAS", kpi_card_style_lbl),
        ],
    ]
    kpi_table = Table(kpi_table_data, colWidths=[135, 135, 135, 135])
    kpi_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5f9")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("PADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(kpi_table)
    story.append(Spacer(1, 20))

    # Section 1: Resumen por Tipo de Visita
    types = report_data.get("types", [])
    if types:
        story.append(Paragraph("1. Resumen por Tipo de Visita", section_heading))
        t_table_data = [
            [
                Paragraph("Tipo de Visita", cell_head),
                Paragraph("Cantidad", cell_head_right),
                Paragraph("Horas Registradas", cell_head_right),
                Paragraph("% del Total Horas", cell_head_right),
            ]
        ]
        for t_row in types:
            t_table_data.append(
                [
                    Paragraph(t_row["visit_type"], cell_body_bold),
                    Paragraph(str(t_row["visit_count"]), cell_body_right),
                    Paragraph(f"{t_row['hours_logged']:.2f} hrs", cell_body_right_bold),
                    Paragraph(f"{t_row['percentage']:.1f}%", cell_body_right),
                ]
            )
        t_table = Table(t_table_data, colWidths=[240, 80, 110, 110])
        t_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("PADDING", (0, 0), (-1, -1), 5),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ]
            )
        )
        story.append(t_table)
        story.append(Spacer(1, 18))

    # Section 2: Resumen por Cliente
    clients = report_data.get("clients", [])
    if clients:
        story.append(Paragraph("2. Resumen de Visitas por Cliente", section_heading))
        c_table_data = [
            [
                Paragraph("Cliente / Empresa", cell_head),
                Paragraph("Programadas", cell_head_right),
                Paragraph("No Programadas", cell_head_right),
                Paragraph("Total Visitas", cell_head_right),
                Paragraph("Horas Registradas", cell_head_right),
            ]
        ]
        for c_row in clients[:25]:
            c_table_data.append(
                [
                    Paragraph(c_row["client_name"], cell_body_bold),
                    Paragraph(str(c_row["scheduled_count"]), cell_body_right),
                    Paragraph(str(c_row["unscheduled_count"]), cell_body_right),
                    Paragraph(str(c_row["total_visits"]), cell_body_right_bold),
                    Paragraph(f"{c_row['hours_logged']:.2f} hrs", cell_body_right_bold),
                ]
            )

        c_table = Table(c_table_data, colWidths=[200, 80, 80, 80, 100])
        c_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("PADDING", (0, 0), (-1, -1), 5),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ]
            )
        )
        story.append(c_table)
        story.append(Spacer(1, 18))

    # Section 3: Detalle de Visitas Realizadas
    tickets = report_data.get("tickets", [])
    if tickets:
        story.append(Paragraph("3. Detalle de Visitas Realizadas", section_heading))
        tkt_table_data = [
            [
                Paragraph("Clave", cell_head),
                Paragraph("Fecha", cell_head),
                Paragraph("Resumen / Ticket", cell_head),
                Paragraph("Cliente", cell_head),
                Paragraph("Tipo", cell_head),
                Paragraph("Horas", cell_head_right),
            ]
        ]
        for t_row in tickets[:50]:
            summary_trunc = t_row["summary"]
            if len(summary_trunc) > 35:
                summary_trunc = summary_trunc[:33] + "..."
            tkt_table_data.append(
                [
                    Paragraph(t_row["jira_key"], cell_body_bold),
                    Paragraph(t_row["visit_date"], cell_body),
                    Paragraph(summary_trunc, cell_body),
                    Paragraph(t_row["client_name"], cell_body),
                    Paragraph(t_row["visit_type"], cell_body),
                    Paragraph(f"{t_row['hours_logged']:.2f} h", cell_body_right_bold),
                ]
            )

        tkt_table = Table(tkt_table_data, colWidths=[60, 65, 175, 110, 80, 50])
        tkt_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("PADDING", (0, 0), (-1, -1), 4),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ]
            )
        )
        story.append(tkt_table)

    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer.getvalue()
