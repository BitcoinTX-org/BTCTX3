from datetime import datetime, timezone
from typing import Dict, Any, List
from decimal import Decimal, ROUND_HALF_DOWN

from sqlalchemy.orm import Session

from backend.models.transaction import (
    Transaction,
    LedgerEntry,
    BitcoinLot,
    LotDisposal
)
from backend.models.account import Account
from backend.services.transaction import recalculate_all_transactions
from backend.services.calculation import (
    get_all_account_balances,
    get_gains_and_losses,
    get_average_cost_basis,
)
import logging


def generate_report_data(db: Session, year: int) -> Dict[str, Any]:
    """
    A comprehensive aggregator that:
      1) Re-lots everything (scorched earth).
      2) Fetches all Transactions in [year-01-01..12-31].
      3) Builds typical summaries (capital gains, income, EOY balances, etc.),
         plus *ALL* available data from these models:
         - Transaction (including from_account_id, to_account_id, fee_amount, etc.)
         - LedgerEntry (optional)
         - BitcoinLot
         - LotDisposal
         - Additional derived data from 'calculation.py' (account balances, overall gains).
    
    This is intentionally very verbose, so you can pick & choose which fields
    to actually use in your final PDF or other reports.
    """

    # 1) Re-lot everything
    recalculate_all_transactions(db)

    # 2) Build date range
    start_dt = datetime(year, 1, 1, tzinfo=timezone.utc)
    end_dt = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    # Query transactions in range
    txns = (
        db.query(Transaction)
          .filter(Transaction.timestamp >= start_dt, Transaction.timestamp <= end_dt)
          .order_by(Transaction.timestamp.asc(), Transaction.id.asc())
          .all()
    )

    # ---------------------------
    # (A) Summaries
    # ---------------------------
    gains_dict = _build_capital_gains_summary(txns)
    income_dict = _build_income_summary(txns)
    asset_list = _build_asset_summary(txns)
    eoy_list = _build_end_of_year_balances(db, end_dt)
    cap_gain_txs = _build_capital_gains_transactions(txns)
    income_txs = _build_income_transactions(txns)
    gifts_lost = _build_gifts_donations_lost(txns)
    expense_list = _build_expenses_list(txns)
    data_sources_list = _gather_data_sources(txns)

    # Additional “comprehensive” data
    all_txn_data = _build_all_transactions_data(txns)
    lot_disposals_data = _build_lot_disposals_for_period(db, start_dt, end_dt)

    # Optionally gather ledger entries in that period
    ledger_entries_data = _build_ledger_entries_for_period(db, start_dt, end_dt)

    # Optionally gather account-level info
    account_balances_data = get_all_account_balances(db)  # from calculation.py
    overall_calcs = get_gains_and_losses(db)              # from calculation.py
    average_btc_basis = get_average_cost_basis(db)        # from calculation.py

    # 3) Construct final dictionary
    #    Feel free to omit any you don’t need
    result = {
        "tax_year": year,
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "period": f"{year}-01-01 to {year}-12-31",

        # Summaries
        "capital_gains_summary": gains_dict,
        "income_summary": income_dict,
        "asset_summary": asset_list,
        "end_of_year_balances": eoy_list,

        "capital_gains_transactions": cap_gain_txs,
        "income_transactions": income_txs,
        "gifts_donations_lost": gifts_lost,
        "expenses": expense_list,

        "data_sources": data_sources_list,

        # Full raw data
        "all_transactions": all_txn_data,
        "lot_disposals": lot_disposals_data,
        "ledger_entries": ledger_entries_data,

        # Additional derived data from calculation.py
        "account_balances": account_balances_data,
        "overall_calcs": overall_calcs,
        "average_btc_cost_basis": float(average_btc_basis),
    }
    return result


# --------------------------------------------------------------------------
# CAPITAL GAINS SUMMARY
# --------------------------------------------------------------------------

def _build_capital_gains_summary(txns: List[Transaction]) -> Dict[str, Any]:
    """
    Summarize short-term vs. long-term gains by reading each transaction
    that disposed BTC (Sell/Withdrawal) where realized_gain_usd is non-null.
    """
    st_proceeds = Decimal("0.0")
    st_basis    = Decimal("0.0")
    st_gain     = Decimal("0.0")

    lt_proceeds = Decimal("0.0")
    lt_basis    = Decimal("0.0")
    lt_gain     = Decimal("0.0")

    disposal_count = 0

    for tx in txns:
        if tx.type not in ("Sell", "Withdrawal"):
            continue
        if tx.realized_gain_usd is None:
            continue

        disposal_count += 1

        proceeds = tx.proceeds_usd or Decimal("0.0")
        basis    = tx.cost_basis_usd or Decimal("0.0")
        gain     = tx.realized_gain_usd or Decimal("0.0")

        if tx.holding_period == "LONG":
            lt_proceeds += proceeds
            lt_basis    += basis
            lt_gain     += gain
        else:
            st_proceeds += proceeds
            st_basis    += basis
            st_gain     += gain

    total_proceeds = st_proceeds + lt_proceeds
    total_basis = st_basis + lt_basis
    net_gains = st_gain + lt_gain

    return {
        "number_of_disposals": disposal_count,
        "short_term": {
            "proceeds": float(st_proceeds),
            "basis":    float(st_basis),
            "gain":     float(st_gain),
        },
        "long_term": {
            "proceeds": float(lt_proceeds),
            "basis":    float(lt_basis),
            "gain":     float(lt_gain),
        },
        "total": {
            "proceeds": float(total_proceeds),
            "basis":    float(total_basis),
            "gain":     float(net_gains),
        }
    }


# --------------------------------------------------------------------------
# INCOME SUMMARY
# --------------------------------------------------------------------------

def _build_income_summary(txns: List[Transaction]) -> Dict[str, Any]:
    """
    Summarize deposit-based income by scanning for Deposit + recognized 'source'.
    """
    total_income = Decimal("0.0")
    mining_total = Decimal("0.0")
    reward_total = Decimal("0.0")
    other_income = Decimal("0.0")

    for tx in txns:
        if tx.type != "Deposit" or not tx.source:
            continue

        deposit_usd_value = tx.cost_basis_usd or Decimal("0.0")
        src_lower = tx.source.lower()

        if "mining" in src_lower:
            mining_total += deposit_usd_value
            total_income += deposit_usd_value
        elif "reward" in src_lower or "interest" in src_lower:
            reward_total += deposit_usd_value
            total_income += deposit_usd_value
        else:
            other_income += deposit_usd_value
            total_income += deposit_usd_value

    return {
        "Mining": float(mining_total),
        "Reward": float(reward_total),
        "Other":  float(other_income),
        "Total":  float(total_income),
    }


# --------------------------------------------------------------------------
# ASSET SUMMARY
# --------------------------------------------------------------------------

def _build_asset_summary(txns: List[Transaction]) -> List[Dict[str, Any]]:
    """
    Currently returns a dummy row for BTC. If you want multi-asset breakdown,
    you'd group transactions or partial-lots by their currency.
    """
    return [
        {"asset": "BTC", "profit": 32031.99, "loss": 3150.70, "net": 28881.29}
    ]


# --------------------------------------------------------------------------
# END OF YEAR BALANCES (LOTS)
# --------------------------------------------------------------------------

def _build_end_of_year_balances(db: Session, end_dt: datetime) -> List[Dict[str, Any]]:
    """
    Summarize leftover BTC from open lots as of 'end_dt'.
    """
    open_lots = (
        db.query(BitcoinLot)
          .filter(BitcoinLot.remaining_btc > 0, BitcoinLot.acquired_date <= end_dt)
          .order_by(BitcoinLot.acquired_date.asc())
          .all()
    )

    # Demo EOY price
    eoy_price = Decimal("94153.13")

    rows = []
    total_btc = Decimal("0.0")
    total_cost = Decimal("0.0")
    total_value = Decimal("0.0")

    for lot in open_lots:
        rem_btc = lot.remaining_btc
        if lot.total_btc and lot.total_btc > 0:
            fraction = rem_btc / lot.total_btc
        else:
            fraction = Decimal("1")
        cost_basis_usd = lot.cost_basis_usd or Decimal("0.0")
        partial_cost = (cost_basis_usd * fraction).quantize(Decimal("0.01"), ROUND_HALF_DOWN)

        cur_value = (rem_btc * eoy_price).quantize(Decimal("0.01"), ROUND_HALF_DOWN)

        rows.append({
            "lot_id": lot.id,
            "asset": "BTC",
            "acquired_date": lot.acquired_date.isoformat() if lot.acquired_date else None,
            "quantity": float(rem_btc),
            "cost": float(partial_cost),
            "value": float(cur_value),
            "description": f"EOY approx @ ${eoy_price} / BTC"
        })

        total_btc += rem_btc
        total_cost += partial_cost
        total_value += cur_value

    rows.append({
        "lot_id": None,
        "asset": "TOTAL",
        "acquired_date": None,
        "quantity": float(total_btc),
        "cost": float(total_cost),
        "value": float(total_value),
        "description": "",
    })
    return rows


# --------------------------------------------------------------------------
# CAPITAL GAINS TRANSACTIONS (DETAILED)
# --------------------------------------------------------------------------

def _build_capital_gains_transactions(txns: List[Transaction]) -> List[Dict[str, Any]]:
    """
    A single-line record for each transaction that realized a gain.
    """
    results = []
    for tx in txns:
        if tx.type not in ("Sell", "Withdrawal"):
            continue
        if tx.realized_gain_usd is None or tx.realized_gain_usd == 0:
            continue

        results.append({
            "tx_id": tx.id,
            "date_sold": tx.timestamp.isoformat() if tx.timestamp else None,
            "date_acquired": "(multiple lots)",
            "asset": "BTC",
            "amount": float(tx.amount or 0),
            "cost": float(tx.cost_basis_usd or 0),
            "proceeds": float(tx.proceeds_usd or 0),
            "gain_loss": float(tx.realized_gain_usd or 0),
            "holding_period": tx.holding_period,
        })
    return results


def _build_income_transactions(txns: List[Transaction]) -> List[Dict[str, Any]]:
    """
    A single-line record for each Deposit that is recognized as “income” (source).
    """
    results = []
    for tx in txns:
        if tx.type != "Deposit" or not tx.source:
            continue
        # You might refine detection logic
        results.append({
            "tx_id": tx.id,
            "date": tx.timestamp.isoformat() if tx.timestamp else None,
            "asset": "BTC",  # or detect if it's a BTC deposit
            "amount": float(tx.amount or 0),
            "value_usd": float(tx.cost_basis_usd or 0),
            "source": tx.source,
            "type": "Reward" if "reward" in tx.source.lower() else "Other",
        })
    return results


def _build_gifts_donations_lost(txns: List[Transaction]) -> List[Dict[str, Any]]:
    """
    All withdrawals with purpose in ('gift','donation','lost').
    """
    results = []
    for tx in txns:
        if tx.type == "Withdrawal" and tx.purpose:
            p = tx.purpose.lower()
            if p in ("gift", "donation", "lost"):
                results.append({
                    "tx_id": tx.id,
                    "date": tx.timestamp.isoformat() if tx.timestamp else None,
                    "asset": "BTC",
                    "amount": float(tx.amount or 0),
                    "value_usd": float(tx.proceeds_usd or 0),
                    "purpose": tx.purpose,
                })
    return results


def _build_expenses_list(txns: List[Transaction]) -> List[Dict[str, Any]]:
    """
    All withdrawals with purpose=Expenses.
    """
    results = []
    for tx in txns:
        if tx.type == "Withdrawal" and tx.purpose and tx.purpose.lower() == "expenses":
            results.append({
                "tx_id": tx.id,
                "date": tx.timestamp.isoformat() if tx.timestamp else None,
                "asset": "BTC",
                "amount": float(tx.amount or 0),
                "value_usd": float(tx.proceeds_usd or 0),
                "type": "Expense",
            })
    return results


# --------------------------------------------------------------------------
# DATA SOURCES
# --------------------------------------------------------------------------

def _gather_data_sources(txns: List[Transaction]) -> List[str]:
    """
    Gather unique .source fields from these transactions.
    """
    sources = set()
    for tx in txns:
        if tx.source:
            sources.add(tx.source)
    return sorted(list(sources))


# --------------------------------------------------------------------------
# ALL TRANSACTIONS DATA (FULL FIELDS)
# --------------------------------------------------------------------------

def _build_all_transactions_data(txns: List[Transaction]) -> List[Dict[str, Any]]:
    """
    Return a big dictionary for each Transaction, including from_account_id,
    to_account_id, fee_amount, fee_currency, is_locked, created_at, updated_at, etc.
    """
    results = []
    for tx in txns:
        row = {
            "id": tx.id,
            "timestamp": tx.timestamp.isoformat() if tx.timestamp else None,
            "type": tx.type,
            "from_account_id": tx.from_account_id,
            "to_account_id": tx.to_account_id,
            "amount": float(tx.amount or 0),
            "fee_amount": float(tx.fee_amount or 0),
            "fee_currency": tx.fee_currency,
            "cost_basis_usd": float(tx.cost_basis_usd or 0),
            "proceeds_usd": float(tx.proceeds_usd or 0),
            "realized_gain_usd": float(tx.realized_gain_usd or 0) if tx.realized_gain_usd else 0,
            "holding_period": tx.holding_period,
            "source": tx.source,
            "purpose": tx.purpose,
            "is_locked": tx.is_locked,
            "created_at": tx.created_at.isoformat() if tx.created_at else None,
            "updated_at": tx.updated_at.isoformat() if tx.updated_at else None,
        }
        results.append(row)
    return results


# --------------------------------------------------------------------------
# LOT DISPOSALS FOR PERIOD
# --------------------------------------------------------------------------

def _build_lot_disposals_for_period(db: Session, start_dt: datetime, end_dt: datetime) -> List[Dict[str, Any]]:
    """
    Returns full details on each LotDisposal whose transaction occurred in [start_dt..end_dt].
    """
    disposals = (
        db.query(LotDisposal)
          .join(Transaction, LotDisposal.transaction_id == Transaction.id)
          .filter(Transaction.timestamp >= start_dt, Transaction.timestamp <= end_dt)
          .order_by(Transaction.timestamp.asc(), LotDisposal.id.asc())
          .all()
    )

    results = []
    for disp in disposals:
        row = {
            "id": disp.id,
            "transaction_id": disp.transaction_id,
            "lot_id": disp.lot_id,
            "disposed_btc": float(disp.disposed_btc or 0),
            "disposal_basis_usd": float(disp.disposal_basis_usd or 0),
            "proceeds_usd_for_that_portion": float(disp.proceeds_usd_for_that_portion or 0),
            "realized_gain_usd": float(disp.realized_gain_usd or 0),
            "holding_period": disp.holding_period,
        }
        results.append(row)
    return results


# --------------------------------------------------------------------------
# LEDGER ENTRIES FOR PERIOD
# --------------------------------------------------------------------------

def _build_ledger_entries_for_period(db: Session, start_dt: datetime, end_dt: datetime) -> List[Dict[str, Any]]:
    """
    Gather all LedgerEntry rows that reference transactions in [start_dt..end_dt].
    Includes account info if desired.
    """
    entries = (
        db.query(LedgerEntry)
          .join(Transaction, LedgerEntry.transaction_id == Transaction.id)
          .filter(Transaction.timestamp >= start_dt, Transaction.timestamp <= end_dt)
          .order_by(Transaction.timestamp.asc(), LedgerEntry.id.asc())
          .all()
    )

    results = []
    for le in entries:
        row = {
            "id": le.id,
            "transaction_id": le.transaction_id,
            "account_id": le.account_id,
            "amount": float(le.amount),
            "currency": le.currency,
            "entry_type": le.entry_type,
            "transaction_timestamp": le.transaction.timestamp.isoformat() if le.transaction.timestamp else None,
            "account_name": le.account.name if le.account else None,
        }
        results.append(row)
    return results
