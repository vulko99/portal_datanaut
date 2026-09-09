from io import BytesIO
import json
from pathlib import Path
from datetime import datetime

from django.conf import settings
from django.core.mail import send_mail
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.drawing.image import Image as XLImage


def home(request):
    return render(request, "landing/home.html")


def demo(request):
    return render(request, "landing/demo.html")


def pricing(request):
    return render(request, "landing/pricing.html")


def about(request):
    return render(request, "landing/about.html")


def roi_calculator(request):
    return render(request, "landing/roi_calculator.html")


def contact(request):
    """
    Прост контакт / request demo – праща имейл и показва success съобщение.
    """
    success = False

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        company = request.POST.get("company", "").strip()
        role = request.POST.get("role", "").strip()
        email = request.POST.get("email", "").strip()
        message = request.POST.get("message", "").strip()

        if name and company and email:
            subject = f"[DataNaut demo] {name} – {company}"
            body = (
                f"Name: {name}\n"
                f"Company: {company}\n"
                f"Role: {role}\n"
                f"Email: {email}\n\n"
                f"Message:\n{message}"
            )

            send_mail(
                subject,
                body,
                getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@datanaut.local"),
                [getattr(settings, "CONTACT_NOTIFY_EMAIL", "your.email@example.com")],
                fail_silently=True,
            )
            success = True

    return render(request, "landing/contact.html", {"success": success})


def for_trading_desks(request):
    return render(request, "landing/for_trading_desks.html")


def for_cfo(request):
    return render(request, "landing/for_cfo.html")


def for_investors(request):
    return render(request, "landing/for_investors.html")


def how_it_works(request):
    return render(request, "landing/how_it_works.html")


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _format_usd(value):
    return f"${value:,.0f}"


def _wrap_text(text, max_width, font_name="Helvetica", font_size=10):
    words = text.split()
    lines = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines


def _draw_wrapped_text(pdf, text, x, y, max_width, line_height=12, font_name="Helvetica", font_size=10):
    lines = _wrap_text(text, max_width, font_name=font_name, font_size=font_size)
    pdf.setFont(font_name, font_size)

    current_y = y
    for line in lines:
        pdf.drawString(x, current_y, line)
        current_y -= line_height

    return current_y


def _get_logo_path():
    base_dir = Path(settings.BASE_DIR)
    logo_path = base_dir / "landing" / "static" / "landing" / "logo.png"
    return logo_path if logo_path.exists() else None


def _draw_logo(pdf, page_width, page_height, margin_x):
    logo_path = _get_logo_path()
    if not logo_path:
        return page_height - 20 * mm

    try:
        logo = ImageReader(str(logo_path))
        img_width, img_height = logo.getSize()

        target_width = 28 * mm
        scale = target_width / img_width
        target_height = img_height * scale

        x = margin_x
        y = page_height - 18 * mm - target_height

        pdf.drawImage(
            logo,
            x,
            y,
            width=target_width,
            height=target_height,
            mask="auto",
            preserveAspectRatio=True,
        )

        return y - 6 * mm
    except Exception:
        return page_height - 20 * mm


def _draw_footer(pdf, page_width, page_number):
    margin_x = 18 * mm
    footer_y = 10 * mm

    pdf.setStrokeColor(colors.HexColor("#D1D5DB"))
    pdf.setLineWidth(0.5)
    pdf.line(margin_x, footer_y + 5 * mm, page_width - margin_x, footer_y + 5 * mm)

    pdf.setFillColor(colors.HexColor("#64748B"))
    pdf.setFont("Helvetica", 8)
    pdf.drawString(margin_x, footer_y, "DataNaut Confidential")
    pdf.drawCentredString(page_width / 2, footer_y, "clients.datanaut@outlook.com")
    pdf.drawRightString(page_width - margin_x, footer_y, f"Page {page_number}")


def _build_report_payload(data):
    company_name = (data.get("company_name") or "Your Company").strip()

    annual_spend_m = _safe_float(data.get("annual_spend_m"), 5.0)
    annual_spend_usd = _safe_int(data.get("annual_spend_usd"), annual_spend_m * 1_000_000)
    terminals = _safe_int(data.get("terminals"), 500)
    zombie_rate_percent = _safe_int(data.get("zombie_rate_percent"), 15)

    management_method_key = (data.get("management_method") or "excel").strip().lower()
    management_method_map = {
        "excel": "Excel Spreadsheets",
        "manual": "Manual Tracking",
        "none": "No Formal Process",
        "basic": "Basic Software",
    }
    management_method = management_method_map.get(management_method_key, "Excel Spreadsheets")

    zombie_cost_usd = _safe_int(data.get("zombie_cost_usd"), annual_spend_usd * (zombie_rate_percent / 100))
    overlapping_cost_usd = _safe_int(data.get("overlapping_cost_usd"), annual_spend_usd * 0.08)
    manual_cost_default = annual_spend_usd * (0.05 if management_method_key == "none" else 0.03)
    manual_cost_usd = _safe_int(data.get("manual_cost_usd"), manual_cost_default)

    annual_leakage_usd = _safe_int(
        data.get("annual_leakage_usd"),
        zombie_cost_usd + overlapping_cost_usd + manual_cost_usd,
    )

    projected_savings_usd = _safe_int(data.get("projected_savings_usd"), annual_leakage_usd * 0.70)
    payback_months = round(_safe_float(data.get("payback_months"), 0.0), 2)
    labor_hours_recovered = _safe_int(data.get("labor_hours_recovered"), terminals * 2)
    benchmark_position = (data.get("benchmark_position") or "within the expected range").strip()

    conservative_savings_usd = _safe_int(data.get("conservative_savings_usd"), annual_leakage_usd * 0.50)
    target_savings_usd = _safe_int(data.get("target_savings_usd"), annual_leakage_usd * 0.70)
    optimistic_savings_usd = _safe_int(data.get("optimistic_savings_usd"), annual_leakage_usd * 0.90)

    analysis_date = datetime.now().strftime("%B %d, %Y %H:%M")

    return {
        "company_name": company_name,
        "analysis_date": analysis_date,
        "annual_spend_m": annual_spend_m,
        "annual_spend_usd": annual_spend_usd,
        "terminals": terminals,
        "zombie_rate_percent": zombie_rate_percent,
        "management_method": management_method,
        "zombie_cost_usd": zombie_cost_usd,
        "overlapping_cost_usd": overlapping_cost_usd,
        "manual_cost_usd": manual_cost_usd,
        "annual_leakage_usd": annual_leakage_usd,
        "projected_savings_usd": projected_savings_usd,
        "payback_months": payback_months,
        "labor_hours_recovered": labor_hours_recovered,
        "benchmark_position": benchmark_position,
        "conservative_savings_usd": conservative_savings_usd,
        "target_savings_usd": target_savings_usd,
        "optimistic_savings_usd": optimistic_savings_usd,
    }


@require_POST
def export_report_pdf(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
        report = _build_report_payload(data)

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4

        margin_x = 18 * mm
        content_width = width - (2 * margin_x)

        y = _draw_logo(pdf, width, height, margin_x)

        def section_title(text):
            nonlocal y
            pdf.setFillColor(colors.HexColor("#0F172A"))
            pdf.setFont("Helvetica-Bold", 14)
            pdf.drawString(margin_x, y, text)
            y -= 8 * mm

        def body_text(text, size=10):
            nonlocal y
            pdf.setFillColor(colors.black)
            y = _draw_wrapped_text(
                pdf,
                text,
                margin_x,
                y,
                content_width,
                line_height=12,
                font_name="Helvetica",
                font_size=size,
            )
            y -= 3 * mm

        pdf.setTitle("DataNaut ROI Report")

        pdf.setFillColor(colors.HexColor("#0F172A"))
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(margin_x, y, "Executive Summary: Market Data Cost Optimization Analysis")
        y -= 10 * mm

        pdf.setFont("Helvetica", 10)
        pdf.setFillColor(colors.black)
        pdf.drawString(margin_x, y, f"Prepared for: {report['company_name']}")
        y -= 6 * mm
        pdf.drawString(margin_x, y, f"Analysis Date: {report['analysis_date']}")
        y -= 6 * mm
        pdf.drawString(margin_x, y, "Tool: DataNaut AI-Powered Benchmarking")
        y -= 10 * mm

        section_title("1. Opportunity Overview")
        body_text(
            f"Based on an annual market data spend of {_format_usd(report['annual_spend_usd'])} and "
            f"a user base of {report['terminals']:,}, our analysis identifies estimated annual leakage "
            f"of {_format_usd(report['annual_leakage_usd'])}. This represents reclaimable spend tied to "
            f"inactive licenses, overlapping feeds, and spreadsheet-led control overhead."
        )

        section_title("2. Financial Impact & ROI")

        metric_rows = [
            ("Projected 12-Month Savings", _format_usd(report["projected_savings_usd"])),
            ("Estimated Monthly Savings", _format_usd(round(report["projected_savings_usd"] / 12))),
            ("Payback Period", f"{report['payback_months']} months"),
            ("Labor Hours Recovered", f"{report['labor_hours_recovered']:,} hours/year"),
        ]

        for label, value in metric_rows:
            pdf.setFont("Helvetica-Bold", 10)
            pdf.drawString(margin_x, y, f"{label}:")
            pdf.setFont("Helvetica", 10)
            pdf.drawString(margin_x + 60 * mm, y, value)
            y -= 6 * mm

        y -= 4 * mm
        section_title("3. Key Findings & Leakage Drivers")

        drivers = [
            (
                "Zombie Licenses",
                report["zombie_cost_usd"],
                "Immediate de-provisioning of inactive or unused terminals via HR-linked review.",
            ),
            (
                "Overlapping Feeds",
                report["overlapping_cost_usd"],
                "Consolidate redundant vendor entitlements and overlapping feed coverage.",
            ),
            (
                "Manual Audit Costs",
                report["manual_cost_usd"],
                "Replace spreadsheet-based review cycles with continuous governance automation.",
            ),
        ]

        for title, amount, recommendation in drivers:
            pdf.setFont("Helvetica-Bold", 10)
            pdf.drawString(margin_x, y, f"{title}: {_format_usd(amount)}")
            y -= 5 * mm
            body_text(recommendation, size=9)

        y -= 2 * mm
        section_title("4. Benchmark Position")
        body_text(
            f"Your current management profile places you {report['benchmark_position']}. "
            f"Moving from {report['management_method']} to DataNaut automation can shift governance "
            f"from periodic review to continuous control."
        )

        _draw_footer(pdf, width, 1)
        pdf.showPage()

        y = _draw_logo(pdf, width, height, margin_x)

        def section_title_page2(text):
            nonlocal y
            pdf.setFillColor(colors.HexColor("#0F172A"))
            pdf.setFont("Helvetica-Bold", 14)
            pdf.drawString(margin_x, y, text)
            y -= 8 * mm

        def body_text_page2(text, size=10):
            nonlocal y
            pdf.setFillColor(colors.black)
            y = _draw_wrapped_text(
                pdf,
                text,
                margin_x,
                y,
                content_width,
                line_height=12,
                font_name="Helvetica",
                font_size=size,
            )
            y -= 3 * mm

        pdf.setFillColor(colors.HexColor("#0F172A"))
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(margin_x, y, "Scenario Analysis & Recovery Roadmap")
        y -= 10 * mm

        section_title_page2("Scenario Analysis")

        scenarios = [
            ("Conservative", "50%", report["conservative_savings_usd"]),
            ("Target", "70%", report["target_savings_usd"]),
            ("Optimistic", "90%", report["optimistic_savings_usd"]),
        ]

        for name, rate, value in scenarios:
            pdf.setFont("Helvetica-Bold", 10)
            pdf.drawString(margin_x, y, f"{name} ({rate})")
            pdf.setFont("Helvetica", 10)
            pdf.drawString(margin_x + 40 * mm, y, _format_usd(value))
            y -= 6 * mm

        y -= 5 * mm
        section_title_page2("Implementation Timeline (Month 1–3)")

        roadmap_rows = [
            ("Phase 1: Inventory Discovery", "Auto-sync HR logs with terminal and entitlement inventory."),
            ("Phase 2: Duplicate Analysis", "Flag redundant user/vendor/feed overlap across desks and entities."),
            ("Phase 3: Governance Automation", "Replace spreadsheet-led controls with continuous policy enforcement."),
        ]

        for title, desc in roadmap_rows:
            pdf.setFont("Helvetica-Bold", 10)
            pdf.drawString(margin_x, y, title)
            y -= 5 * mm
            body_text_page2(desc, size=9)

        y -= 2 * mm
        section_title_page2("Next Step")
        body_text_page2(
            "Use this estimate as a directional internal business case. Review the assumptions, validate "
            "the leakage categories against your vendor mix, and schedule an implementation review with DataNaut."
        )

        y -= 3 * mm
        pdf.setFillColor(colors.HexColor("#065F46"))
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(margin_x, y, "Ready to automate this recovery?")
        y -= 6 * mm

        pdf.setFillColor(colors.black)
        pdf.setFont("Helvetica", 10)
        pdf.drawString(margin_x, y, "Book an implementation review with DataNaut.")
        y -= 5 * mm
        pdf.drawString(margin_x, y, "Email: clients.datanaut@outlook.com")

        _draw_footer(pdf, width, 2)

        pdf.save()
        buffer.seek(0)

        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="datanaut-roi-report.pdf"'
        return response

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


def _apply_title_style(ws, cell_ref):
    cell = ws[cell_ref]
    cell.font = Font(bold=True, color="FFFFFF", size=14)
    cell.fill = PatternFill("solid", fgColor="0F172A")
    cell.alignment = Alignment(horizontal="left", vertical="center")


def _apply_section_header(ws, row, start_col=1, end_col=3, title=""):
    ws.merge_cells(start_row=row, start_column=start_col, end_row=row, end_column=end_col)
    cell = ws.cell(row=row, column=start_col, value=title)
    cell.font = Font(bold=True, color="FFFFFF", size=12)
    cell.fill = PatternFill("solid", fgColor="0F172A")
    cell.alignment = Alignment(horizontal="left", vertical="center")


def _apply_table_header(cell):
    cell.font = Font(bold=True, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor="1E293B")
    cell.alignment = Alignment(horizontal="center", vertical="center")


def _currency_format(cell):
    cell.number_format = '$#,##0;[Red]($#,##0);-'


def _number_format(cell):
    cell.number_format = '#,##0;[Red](#,##0);-'


def _decimal_format(cell):
    cell.number_format = '0.00'


def _thin_bottom_border():
    return Border(bottom=Side(style="thin", color="D1D5DB"))


@require_POST
def export_report_xlsx(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
        report = _build_report_payload(data)

        wb = Workbook()
        ws_summary = wb.active
        ws_summary.title = "Executive Summary"
        ws_breakdown = wb.create_sheet("Detailed Breakdown")
        ws_logic = wb.create_sheet("Logic & Assumptions")
        ws_scenarios = wb.create_sheet("Scenario Analysis")
        ws_roadmap = wb.create_sheet("Recovery Roadmap")
        ws_compare = wb.create_sheet("Current vs DataNaut")

        for ws in wb.worksheets:
            ws.sheet_view.showGridLines = False

        logo_path = _get_logo_path()
        if logo_path:
            try:
                img = XLImage(str(logo_path))
                img.width = 120
                img.height = 50
                ws_summary.add_image(img, "A1")
            except Exception:
                pass

        ws_summary.column_dimensions["A"].width = 28
        ws_summary.column_dimensions["B"].width = 24
        ws_summary.column_dimensions["C"].width = 70

        ws_summary.merge_cells("A5:C5")
        ws_summary["A5"] = "EXECUTIVE SUMMARY: Market Data Cost Optimization Analysis"
        _apply_title_style(ws_summary, "A5")
        ws_summary.row_dimensions[5].height = 24

        ws_summary["A7"] = "Prepared for:"
        ws_summary["B7"] = report["company_name"]
        ws_summary["A8"] = "Analysis Date:"
        ws_summary["B8"] = report["analysis_date"]
        ws_summary["A9"] = "Tool:"
        ws_summary["B9"] = "DataNaut AI-Powered Benchmarking"

        for cell_ref in ["A7", "A8", "A9"]:
            ws_summary[cell_ref].font = Font(bold=True)

        _apply_section_header(ws_summary, 11, 1, 3, "1. Opportunity Overview")
        ws_summary.merge_cells("A12:C12")
        ws_summary["A12"] = (
            f"Based on an annual market data spend of {_format_usd(report['annual_spend_usd'])} "
            f"and a user base of {report['terminals']:,}, our analysis identifies estimated annual leakage "
            f"of {_format_usd(report['annual_leakage_usd'])}. This represents reclaimable spend tied to inactive "
            f"licenses, overlapping feeds, and spreadsheet-led control overhead."
        )
        ws_summary["A12"].alignment = Alignment(wrap_text=True, vertical="top")

        _apply_section_header(ws_summary, 14, 1, 3, "2. Financial Impact & ROI")
        summary_metrics = [
            ("Projected 12-Month Savings", report["projected_savings_usd"]),
            ("Estimated Monthly Savings", round(report["projected_savings_usd"] / 12)),
            ("Payback Period (months)", report["payback_months"]),
            ("Labor Hours Recovered", report["labor_hours_recovered"]),
        ]
        row = 15
        for label, value in summary_metrics:
            ws_summary[f"A{row}"] = label
            ws_summary[f"A{row}"].font = Font(bold=True)
            ws_summary[f"B{row}"] = value
            if "months" in label.lower():
                _decimal_format(ws_summary[f"B{row}"])
            elif "Hours" in label:
                _number_format(ws_summary[f"B{row}"])
            else:
                _currency_format(ws_summary[f"B{row}"])
            row += 1

        _apply_section_header(ws_summary, 20, 1, 3, "3. Key Findings & Leakage Drivers")
        headers = ["Leakage Category", "Estimated Annual Loss", "Strategic Recommendation"]
        for col, header in enumerate(headers, start=1):
            cell = ws_summary.cell(row=21, column=col, value=header)
            _apply_table_header(cell)

        drivers = [
            ("Zombie Licenses", report["zombie_cost_usd"], "Immediate de-provisioning of inactive or unused terminals via HR-linked review."),
            ("Overlapping Feeds", report["overlapping_cost_usd"], "Consolidate redundant vendor entitlements and overlapping feed coverage."),
            ("Manual Audit Costs", report["manual_cost_usd"], "Replace spreadsheet-based review cycles with continuous governance automation."),
        ]
        row = 22
        for name, amount, recommendation in drivers:
            ws_summary.cell(row=row, column=1, value=name)
            amount_cell = ws_summary.cell(row=row, column=2, value=amount)
            _currency_format(amount_cell)
            ws_summary.cell(row=row, column=3, value=recommendation)
            row += 1

        _apply_section_header(ws_summary, 27, 1, 3, "4. Benchmark Position")
        ws_summary.merge_cells("A28:C28")
        ws_summary["A28"] = (
            f"Your current management profile places you {report['benchmark_position']}. "
            f"Transitioning from {report['management_method']} to DataNaut Automation shifts control "
            f"from periodic review to continuous governance."
        )
        ws_summary["A28"].alignment = Alignment(wrap_text=True, vertical="top")

        _apply_section_header(ws_summary, 30, 1, 3, "Next Steps")
        next_steps = [
            ("Validation", "Review the Detailed Breakdown tab for math and assumptions."),
            ("Pilot", "Initiate a discovery scan to identify user-level redundancies."),
            ("Contact", "clients.datanaut@outlook.com"),
        ]
        row = 31
        for label, text in next_steps:
            ws_summary[f"A{row}"] = label
            ws_summary[f"A{row}"].font = Font(bold=True)
            ws_summary[f"B{row}"] = text
            row += 1

        ws_breakdown.column_dimensions["A"].width = 38
        ws_breakdown.column_dimensions["B"].width = 20
        _apply_section_header(ws_breakdown, 1, 1, 2, "Detailed Breakdown")
        rows = [
            ("Company Name", report["company_name"]),
            ("Annual Market Data Spend (USD)", report["annual_spend_usd"]),
            ("Annual Market Data Spend ($M)", report["annual_spend_m"]),
            ("Number of Terminals / Users", report["terminals"]),
            ("Zombie License Rate (%)", report["zombie_rate_percent"]),
            ("Management Method", report["management_method"]),
            ("Zombie Cost (USD)", report["zombie_cost_usd"]),
            ("Overlapping Feed Cost (USD)", report["overlapping_cost_usd"]),
            ("Manual Audit Cost (USD)", report["manual_cost_usd"]),
            ("Estimated Annual Leakage (USD)", report["annual_leakage_usd"]),
            ("Projected 12-Month Savings (USD)", report["projected_savings_usd"]),
            ("Conservative Savings (USD)", report["conservative_savings_usd"]),
            ("Target Savings (USD)", report["target_savings_usd"]),
            ("Optimistic Savings (USD)", report["optimistic_savings_usd"]),
            ("Payback Period (months)", report["payback_months"]),
            ("Labor Hours Recovered", report["labor_hours_recovered"]),
            ("Benchmark Position", report["benchmark_position"]),
        ]
        row = 3
        for label, value in rows:
            ws_breakdown[f"A{row}"] = label
            ws_breakdown[f"A{row}"].font = Font(bold=True)
            ws_breakdown[f"B{row}"] = value
            if isinstance(value, (int, float)):
                if "USD" in label:
                    _currency_format(ws_breakdown[f"B{row}"])
                elif "months" in label:
                    _decimal_format(ws_breakdown[f"B{row}"])
                elif "%" in label:
                    _number_format(ws_breakdown[f"B{row}"])
                else:
                    _number_format(ws_breakdown[f"B{row}"])
            row += 1

        ws_logic.column_dimensions["A"].width = 28
        ws_logic.column_dimensions["B"].width = 60
        _apply_section_header(ws_logic, 1, 1, 2, "Logic & Assumptions")
        logic_rows = [
            ("Zombie Licenses", "Annual Spend × Zombie Rate"),
            ("Overlapping Feeds", "Annual Spend × 8% redundancy benchmark"),
            ("Manual Audit Cost", "Annual Spend × process overhead by current management method"),
            ("Target Savings", "Total Leakage × 70% recovery rate"),
            ("Conservative Savings", "Total Leakage × 50% recovery rate"),
            ("Optimistic Savings", "Total Leakage × 90% recovery rate"),
        ]
        row = 3
        for label, formula_text in logic_rows:
            ws_logic[f"A{row}"] = label
            ws_logic[f"A{row}"].font = Font(bold=True)
            ws_logic[f"B{row}"] = formula_text
            row += 1

        ws_scenarios.column_dimensions["A"].width = 20
        ws_scenarios.column_dimensions["B"].width = 18
        ws_scenarios.column_dimensions["C"].width = 22
        _apply_section_header(ws_scenarios, 1, 1, 3, "Scenario Analysis")
        for idx, header in enumerate(["Scenario", "Recovery Rate", "Savings (USD)"], start=1):
            _apply_table_header(ws_scenarios.cell(row=3, column=idx, value=header))
        scenario_rows = [
            ("Conservative", "50%", report["conservative_savings_usd"]),
            ("Target", "70%", report["target_savings_usd"]),
            ("Optimistic", "90%", report["optimistic_savings_usd"]),
        ]
        row = 4
        for name, rate, amount in scenario_rows:
            ws_scenarios.cell(row=row, column=1, value=name)
            ws_scenarios.cell(row=row, column=2, value=rate)
            val_cell = ws_scenarios.cell(row=row, column=3, value=amount)
            _currency_format(val_cell)
            row += 1

        ws_roadmap.column_dimensions["A"].width = 24
        ws_roadmap.column_dimensions["B"].width = 64
        ws_roadmap.column_dimensions["C"].width = 24
        _apply_section_header(ws_roadmap, 1, 1, 3, "Recovery Roadmap")
        for idx, header in enumerate(["Phase", "Key Action", "Estimated Savings Realized"], start=1):
            _apply_table_header(ws_roadmap.cell(row=3, column=idx, value=header))
        roadmap_rows = [
            ("Phase 1: Inventory Discovery", "Auto-sync HR logs with terminal inventories and identify inactive users.", round(report["annual_leakage_usd"] * 0.35)),
            ("Phase 2: Duplicate Analysis", "Flag overlapping feed coverage across vendors, desks, and users.", round(report["annual_leakage_usd"] * 0.30)),
            ("Phase 3: Governance Automation", "Replace spreadsheet-led controls with continuous monitoring and workflow.", round(report["annual_leakage_usd"] * 0.35)),
        ]
        row = 4
        for phase, action, amount in roadmap_rows:
            ws_roadmap.cell(row=row, column=1, value=phase)
            ws_roadmap.cell(row=row, column=2, value=action)
            val_cell = ws_roadmap.cell(row=row, column=3, value=amount)
            _currency_format(val_cell)
            row += 1

        ws_compare.column_dimensions["A"].width = 28
        ws_compare.column_dimensions["B"].width = 32
        ws_compare.column_dimensions["C"].width = 32
        _apply_section_header(ws_compare, 1, 1, 3, "Current vs DataNaut")
        for idx, header in enumerate(["Feature", "Your Current", "DataNaut SaaS"], start=1):
            _apply_table_header(ws_compare.cell(row=3, column=idx, value=header))
        compare_rows = [
            ("Audit Frequency", "Annual / Quarterly", "Real-time / 24x7"),
            ("Accuracy", "60–70% (Manual Error Risk)", "99.9% (API-Driven)"),
            ("Cost to Manage", report["manual_cost_usd"], 50000),
            ("Redundancy Detection", "Ad hoc / spreadsheet-led", "Continuous duplicate feed detection"),
            ("Control Trail", "Email + spreadsheet notes", "Centralized governance record"),
        ]
        row = 4
        for feature, current, future in compare_rows:
            ws_compare.cell(row=row, column=1, value=feature)
            c2 = ws_compare.cell(row=row, column=2, value=current)
            c3 = ws_compare.cell(row=row, column=3, value=future)
            if isinstance(current, (int, float)):
                _currency_format(c2)
            if isinstance(future, (int, float)):
                _currency_format(c3)
            row += 1

        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
            for row_idx in range(1, ws.max_row + 1):
                ws.row_dimensions[row_idx].height = 20

        output = BytesIO()
        wb.save(output)
        output.seek(0)

        response = HttpResponse(
            output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="datanaut-roi-report.xlsx"'
        return response

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)