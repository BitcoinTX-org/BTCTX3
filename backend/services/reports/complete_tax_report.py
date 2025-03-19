from typing import Dict, Any, List
from io import BytesIO

from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak,
    TableOfContents
)
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def generate_comprehensive_tax_report(report_dict: Dict[str, Any]) -> bytes:
    """
    Generates a 'Comprehensive Tax Report' that attempts to mimic Koinly's style:
      - Cover Title & Metadata
      - Table of Contents
      - Summaries (Capital Gains, Income, Asset Summary)
      - Detailed Sections (Capital Gains Txs, Income Txs, Gifts, Expenses, EOY Balances)
      - Additional Data:
         * All Transactions (raw)
         * Lot Disposal Details
         * Ledger Entries
         * Account Balances, Overall Calculations
      - Data Sources
      - Disclaimers/Methodology
    """

    # Prepare in-memory buffer for PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)

    styles = getSampleStyleSheet()

    # Additional paragraph styles for headings & TOC
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

    # (Optional) disclaimers or methodology at front
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

    # Helper to add a heading that appears in TOC
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
            ["Short-Term",
             short_term.get("proceeds", 0),
             short_term.get("basis", 0),
             short_term.get("gain", 0)],
            ["Long-Term",
             long_term.get("proceeds", 0),
             long_term.get("basis", 0),
             long_term.get("gain", 0)],
            ["Total",
             total.get("proceeds", 0),
             total.get("basis", 0),
             total.get("gain", 0)],
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
            data.append([
                item.get("asset", ""),
                f"{item.get('profit', 0):.2f}",
                f"{item.get('loss', 0):.2f}",
                f"{item.get('net', 0):.2f}",
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
            tx_data.append([
                tx.get("date_sold", ""),
                tx.get("date_acquired", ""),
                tx.get("asset", ""),
                f"{tx.get('amount', 0):.8f}",
                f"${tx.get('cost', 0):.2f}",
                f"${tx.get('proceeds', 0):.2f}",
                f"${tx.get('gain_loss', 0):.2f}",
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
            inc_data.append([
                i_tx.get("date", ""),
                i_tx.get("asset", ""),
                f"{i_tx.get('amount', 0):.8f}",
                f"${i_tx.get('value_usd', 0):.2f}",
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
            table_data.append([
                row.get("date", ""),
                row.get("asset", ""),
                f"{row.get('amount', 0):.8f}",
                f"${row.get('value_usd', 0):.2f}",
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
            table_data.append([
                row.get("date", ""),
                row.get("asset", ""),
                f"{row.get('amount', 0):.8f}",
                f"${row.get('value_usd', 0):.2f}",
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
            bal_data.append([
                bal.get("asset", ""),
                f"{bal.get('quantity', 0):.8f}",
                f"${bal.get('cost', 0):.2f}",
                f"${bal.get('value', 0):.2f}",
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
        # Example columns: id, timestamp, type, from_account_id, to_account_id, etc.
        header = [
            "ID", "Date", "Type", "FromAcct", "ToAcct",
            "Amount", "Fee", "FeeCur", "CostBasisUSD",
            "ProceedsUSD", "RealGainUSD", "HoldPer", "Source",
            "Purpose", "IsLocked", "CreatedAt", "UpdatedAt"
        ]
        data = [header]
        for t in all_txs:
            data.append([
                t.get("id", ""),
                t.get("timestamp", ""),
                t.get("type", ""),
                t.get("from_account_id", ""),
                t.get("to_account_id", ""),
                f"{t.get('amount', 0):.8f}",
                f"{t.get('fee_amount', 0):.8f}",
                t.get("fee_currency", ""),
                f"{t.get('cost_basis_usd', 0):.2f}",
                f"{t.get('proceeds_usd', 0):.2f}",
                f"{t.get('realized_gain_usd', 0):.2f}",
                t.get("holding_period", ""),
                t.get("source", ""),
                t.get("purpose", ""),
                str(t.get("is_locked", "")),
                t.get("created_at", ""),
                t.get("updated_at", "")
            ])
        table = Table(data, repeatRows=1)
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
            data.append([
                d.get("id", ""),
                d.get("transaction_id", ""),
                d.get("lot_id", ""),
                f"{d.get('disposed_btc', 0):.8f}",
                f"{d.get('cost_basis_usd', 0):.2f}",
                f"{d.get('proceeds_usd', 0):.2f}",
                f"{d.get('gain_usd', 0):.2f}",
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
            data.append([
                le.get("id", ""),
                le.get("transaction_id", ""),
                le.get("account_id", ""),
                f"{le.get('amount', 0):.8f}",
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
    # 13) Account Balances, Gains & Losses (From calculation.py)
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
                str(ab.get("balance", "")),
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
        # Here we can just do a quick text dump or pick relevant fields
        # E.g. short_term_gains, short_term_losses, total_net_capital_gains, fees, etc.
        text_lines = []
        for k, v in overall_calcs.items():
            text_lines.append(f"<b>{k}:</b> {v}")
        story.append(Paragraph("<br/>".join(text_lines), styles["Normal"]))
        story.append(Spacer(1, 12))

    avg_btc_cb = report_dict.get("average_btc_cost_basis", None)
    if avg_btc_cb is not None:
        story.append(Paragraph(f"<b>Average BTC Cost Basis:</b> ${avg_btc_cb:.2f}", styles["Normal"]))
        story.append(Spacer(1, 12))

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
