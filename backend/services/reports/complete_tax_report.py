# File: backend/services/reports/complete_tax_report.py
from typing import Dict, Any, List
from io import BytesIO

from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak,
    TableOfContents
)
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch


def generate_comprehensive_tax_report(report_dict: Dict[str, Any]) -> bytes:
    """
    Generates a 'Comprehensive Tax Report' with extended detail sections but
    ensures the PDF still builds successfully (avoiding table layout issues, etc.).
    """

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(name='Heading1', parent=styles['Heading1'], spaceAfter=6)
    h2 = ParagraphStyle(name='Heading2', parent=styles['Heading2'], spaceAfter=4)

    story: List = []

    # ------------------------------------------------------------------
    # 0) Cover / Title Page
    # ------------------------------------------------------------------
    tax_year = report_dict.get("tax_year", "Unknown Year")
    report_date = report_dict.get("report_date", "Unknown Date")
    period = report_dict.get("period", "")

    title_para = Paragraph("<b>BitcoinTX Comprehensive Tax Report</b>", h1)
    story.append(title_para)

    meta_text = (
        f"<b>Tax Year:</b> {tax_year}<br/>"
        f"<b>Report Date:</b> {report_date}<br/>"
        f"<b>Period:</b> {period}"
    )
    story.append(Paragraph(meta_text, styles["Normal"]))
    story.append(Spacer(1, 12))

    disclaimers = report_dict.get("disclaimers", "")
    if disclaimers:
        story.append(Paragraph("<b>Disclaimers & Methodology</b>", h2))
        story.append(Paragraph(disclaimers, styles["Normal"]))
        story.append(Spacer(1, 12))

    # Force a page break
    story.append(PageBreak())

    # ------------------------------------------------------------------
    # 1) Table of Contents
    # ------------------------------------------------------------------
    story.append(Paragraph("Table of Contents", h1))
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(
            fontName='Helvetica-Bold',
            fontSize=12,
            name='TOCHeading1',
            leftIndent=20,
            firstLineIndent=-20,
            spaceBefore=5
        ),
        ParagraphStyle(
            fontName='Helvetica',
            fontSize=10,
            name='TOCHeading2',
            leftIndent=40,
            firstLineIndent=-20,
            spaceBefore=2
        ),
    ]
    story.append(toc)
    story.append(Spacer(1, 12))
    story.append(PageBreak())

    def add_section_heading(text: str, level: int = 1):
        style = h1 if level == 1 else h2
        para = Paragraph(text, style)
        para.outline = True
        para.outlineLevel = level
        story.append(para)

    # ------------------------------------------------------------------
    # 2) Capital Gains Summary
    # ------------------------------------------------------------------
    cg_summary = report_dict.get("capital_gains_summary", {})
    if cg_summary:
        add_section_heading("Capital Gains Summary", 1)
        short_term = cg_summary.get("short_term", {})
        long_term = cg_summary.get("long_term", {})
        total = cg_summary.get("total", {})

        cg_data = [
            ["Type", "Proceeds", "Cost Basis", "Gain/Loss"],
            [
                "Short-Term",
                short_term.get("proceeds", 0),
                short_term.get("basis", 0),
                short_term.get("gain", 0),
            ],
            [
                "Long-Term",
                long_term.get("proceeds", 0),
                long_term.get("basis", 0),
                long_term.get("gain", 0),
            ],
            [
                "Total",
                total.get("proceeds", 0),
                total.get("basis", 0),
                total.get("gain", 0),
            ],
        ]
        table = Table(cg_data)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))

    # ------------------------------------------------------------------
    # 3) Income Summary
    # ------------------------------------------------------------------
    inc_summary = report_dict.get("income_summary", {})
    if inc_summary:
        add_section_heading("Income Summary", 1)
        inc_data = [
            ["Mining", "Reward", "Other", "Total"],
            [
                inc_summary.get("Mining", 0),
                inc_summary.get("Reward", 0),
                inc_summary.get("Other", 0),
                inc_summary.get("Total", 0),
            ]
        ]
        table = Table(inc_data)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("ALIGN", (0, 1), (-1, -1), "RIGHT"),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))

    # ------------------------------------------------------------------
    # 4) Asset Summary
    # ------------------------------------------------------------------
    asset_summary = report_dict.get("asset_summary", [])
    if asset_summary:
        add_section_heading("Asset Summary", 1)
        header = ["Asset", "Profit", "Loss", "Net"]
        data = [header]
        for item in asset_summary:
            profit = float(item.get("profit", 0) or 0)
            loss = float(item.get("loss", 0) or 0)
            net = float(item.get("net", 0) or 0)
            data.append([
                item.get("asset", ""),
                f"{profit:.2f}",
                f"{loss:.2f}",
                f"{net:.2f}",
            ])
        table = Table(data)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))

    story.append(PageBreak())  # New page for Detailed Transactions

    # ------------------------------------------------------------------
    # 5) Capital Gains Transactions (Detailed)
    # ------------------------------------------------------------------
    cg_transactions = report_dict.get("capital_gains_transactions", [])
    if cg_transactions:
        add_section_heading("Capital Gains Transactions (Detailed)", 1)
        tx_data = [
            ["Date Sold", "Date Acquired", "Asset", "Amount",
             "Cost Basis", "Proceeds", "Gain/Loss", "Holding"]
        ]
        for tx in cg_transactions:
            amount = float(tx.get("amount", 0) or 0)
            cost = float(tx.get("cost", 0) or 0)
            proceeds = float(tx.get("proceeds", 0) or 0)
            gain_loss = float(tx.get("gain_loss", 0) or 0)
            tx_data.append([
                tx.get("date_sold", ""),
                tx.get("date_acquired", ""),
                tx.get("asset", ""),
                f"{amount:.8f}",
                f"${cost:.2f}",
                f"${proceeds:.2f}",
                f"${gain_loss:.2f}",
                tx.get("holding_period", "")
            ])
        table = Table(tx_data, repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 1), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))

    # ------------------------------------------------------------------
    # 6) Income Transactions (Detailed)
    # ------------------------------------------------------------------
    inc_transactions = report_dict.get("income_transactions", [])
    if inc_transactions:
        add_section_heading("Income Transactions (Detailed)", 1)
        inc_data = [["Date", "Asset", "Amount", "Value (USD)", "Type", "Description"]]
        for i_tx in inc_transactions:
            amt = float(i_tx.get("amount", 0) or 0)
            val = float(i_tx.get("value_usd", 0) or 0)
            inc_data.append([
                i_tx.get("date", ""),
                i_tx.get("asset", ""),
                f"{amt:.8f}",
                f"${val:.2f}",
                i_tx.get("type", ""),
                i_tx.get("description", ""),
            ])
        table = Table(inc_data, repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (2, 1), (3, -1), "RIGHT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))

    story.append(PageBreak())  # new page for gifts, expenses, EOY

    # ------------------------------------------------------------------
    # 7) Gifts, Donations & Lost Assets
    # ------------------------------------------------------------------
    gifts_list = report_dict.get("gifts_donations_lost", [])
    if gifts_list:
        add_section_heading("Gifts, Donations & Lost Assets", 1)
        table_data = [["Date", "Asset", "Amount", "Value(USD)", "Type"]]
        for row in gifts_list:
            amt = float(row.get("amount", 0) or 0)
            val = float(row.get("value_usd", 0) or 0)
            table_data.append([
                row.get("date", ""),
                row.get("asset", ""),
                f"{amt:.8f}",
                f"${val:.2f}",
                row.get("type", ""),
            ])
        table = Table(table_data, repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))

    # ------------------------------------------------------------------
    # 8) Expenses
    # ------------------------------------------------------------------
    expenses_list = report_dict.get("expenses", [])
    if expenses_list:
        add_section_heading("Expenses", 1)
        table_data = [["Date", "Asset", "Amount", "Value(USD)", "Type"]]
        for row in expenses_list:
            amt = float(row.get("amount", 0) or 0)
            val = float(row.get("value_usd", 0) or 0)
            table_data.append([
                row.get("date", ""),
                row.get("asset", ""),
                f"{amt:.8f}",
                f"${val:.2f}",
                row.get("type", ""),
            ])
        table = Table(table_data, repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))

    # ------------------------------------------------------------------
    # 9) End-of-Year Balances
    # ------------------------------------------------------------------
    eoy_balances = report_dict.get("end_of_year_balances", [])
    if eoy_balances:
        add_section_heading("End of Year Holdings", 1)
        bal_data = [["Asset", "Quantity", "Cost Basis", "Market Value", "Description"]]
        for bal in eoy_balances:
            qty = float(bal.get("quantity", 0) or 0)
            cost = float(bal.get("cost", 0) or 0)
            val = float(bal.get("value", 0) or 0)
            bal_data.append([
                bal.get("asset", ""),
                f"{qty:.8f}",
                f"${cost:.2f}",
                f"${val:.2f}",
                bal.get("description", "")
            ])
        table = Table(bal_data, repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (1, 1), (3, -1), "RIGHT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))

    story.append(PageBreak())  # new page for additional data

    # ------------------------------------------------------------------
    # 10) All Transactions (Raw)
    # ------------------------------------------------------------------
    all_txs = report_dict.get("all_transactions", [])
    if all_txs:
        add_section_heading("All Transactions (Raw Data)", 1)
        header = [
            "ID", "Date", "Type", "FromAcct", "ToAcct",
            "Amount", "Fee", "FeeCur", "CostBasisUSD",
            "ProceedsUSD", "RealGainUSD", "HoldPer", "Source",
            "Purpose", "IsLocked", "CreatedAt", "UpdatedAt"
        ]
        data = [header]
        for t in all_txs:
            try:
                amount = float(t.get('amount', 0) or 0)
            except:
                amount = 0.0
            fee_amount = float(t.get('fee_amount', 0) or 0)
            cost_basis = float(t.get('cost_basis_usd', 0) or 0)
            proceeds = float(t.get('proceeds_usd', 0) or 0)
            realized_gain = float(t.get('realized_gain_usd', 0) or 0)

            data.append([
                t.get("id", ""),
                t.get("timestamp", ""),
                t.get("type", ""),
                t.get("from_account_id", ""),
                t.get("to_account_id", ""),
                f"{amount:.8f}",
                f"{fee_amount:.8f}",
                t.get("fee_currency", ""),
                f"{cost_basis:.2f}",
                f"{proceeds:.2f}",
                f"{realized_gain:.2f}",
                t.get("holding_period", ""),
                t.get("source", ""),
                t.get("purpose", ""),
                str(t.get("is_locked", "")),
                t.get("created_at", ""),
                t.get("updated_at", "")
            ])

        # Constrain column widths so the table can fit on the page
        col_widths = [
            0.6 * inch,  # ID
            0.9 * inch,  # Date
            0.8 * inch,  # Type
            1.0 * inch,  # FromAcct
            1.0 * inch,  # ToAcct
            0.8 * inch,  # Amount
            0.8 * inch,  # Fee
            0.7 * inch,  # FeeCur
            1.0 * inch,  # CostBasisUSD
            1.0 * inch,  # ProceedsUSD
            1.0 * inch,  # RealGainUSD
            0.8 * inch,  # HoldPer
            0.8 * inch,  # Source
            0.8 * inch,  # Purpose
            0.7 * inch,  # IsLocked
            1.0 * inch,  # CreatedAt
            1.0 * inch   # UpdatedAt
        ]

        table = Table(data, repeatRows=1, colWidths=col_widths)
        table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))

    # ------------------------------------------------------------------
    # 11) Lot Disposal Details
    # ------------------------------------------------------------------
    lot_disposals = report_dict.get("lot_disposals", [])
    if lot_disposals:
        add_section_heading("Lot Disposal Details (Partial-Lot Usage)", 1)
        header = [
            "ID", "TxnID", "LotID", "Disposed BTC", "CostBasisUSD",
            "ProceedsUSD", "GainUSD", "HoldingPeriod"
        ]
        data = [header]
        for d in lot_disposals:
            disposed_btc = float(d.get('disposed_btc', 0) or 0)
            cb = float(d.get('cost_basis_usd', 0) or 0)
            pr = float(d.get('proceeds_usd', 0) or 0)
            gn = float(d.get('gain_usd', 0) or 0)
            data.append([
                d.get("id", ""),
                d.get("transaction_id", ""),
                d.get("lot_id", ""),
                f"{disposed_btc:.8f}",
                f"{cb:.2f}",
                f"{pr:.2f}",
                f"{gn:.2f}",
                d.get("holding_period", "")
            ])
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))

    # ------------------------------------------------------------------
    # 12) Ledger Entries
    # ------------------------------------------------------------------
    ledger_entries = report_dict.get("ledger_entries", [])
    if ledger_entries:
        add_section_heading("Ledger Entries", 1)
        header = [
            "ID", "TxnID", "AcctID", "Amount", "Currency",
            "Type", "TxnTimestamp", "AcctName"
        ]
        data = [header]
        for le in ledger_entries:
            amt = float(le.get('amount', 0) or 0)
            data.append([
                le.get("id", ""),
                le.get("transaction_id", ""),
                le.get("account_id", ""),
                f"{amt:.8f}",
                le.get("currency", ""),
                le.get("entry_type", ""),
                le.get("transaction_timestamp", ""),
                le.get("account_name", ""),
            ])
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))

    story.append(PageBreak())

    # ------------------------------------------------------------------
    # 13) Account Balances, Gains & Losses
    # ------------------------------------------------------------------
    acct_balances = report_dict.get("account_balances", [])
    if acct_balances:
        add_section_heading("Account Balances", 1)
        header = ["AcctID", "Name", "Currency", "Balance"]
        data = [header]
        for ab in acct_balances:
            data.append([
                ab.get("account_id", ""),
                ab.get("name", ""),
                ab.get("currency", ""),
                str(ab.get("balance", "0")),
            ])
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))

    overall_calcs = report_dict.get("overall_calcs", {})
    if overall_calcs:
        add_section_heading("Overall Calculations", 1)
        lines = []
        for k, v in overall_calcs.items():
            lines.append(f"<b>{k}:</b> {v}")
        story.append(Paragraph("<br/>".join(lines), styles["Normal"]))
        story.append(Spacer(1, 12))

    avg_btc_cb = report_dict.get("average_btc_cost_basis", None)
    if avg_btc_cb is not None:
        try:
            avg_btc_cb_val = float(avg_btc_cb)
            story.append(Paragraph(f"<b>Average BTC Cost Basis:</b> ${avg_btc_cb_val:.2f}", styles["Normal"]))
            story.append(Spacer(1, 12))
        except (TypeError, ValueError):
            # If it's not numeric, skip or handle gracefully
            pass

    story.append(PageBreak())

    # ------------------------------------------------------------------
    # 14) Data Sources
    # ------------------------------------------------------------------
    data_sources = report_dict.get("data_sources", [])
    if data_sources:
        add_section_heading("Data Sources", 1)
        for source in data_sources:
            story.append(Paragraph(f"- {source}", styles["Normal"]))
        story.append(Spacer(1, 12))

    # Final disclaimers
    final_disclaimer = report_dict.get("final_disclaimer", "")
    if final_disclaimer:
        add_section_heading("Additional Disclaimers", 1)
        story.append(Paragraph(final_disclaimer, styles["Normal"]))
        story.append(Spacer(1, 12))

    # Build the PDF
    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
