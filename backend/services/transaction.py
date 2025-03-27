# FILE: backend/services/transaction.py

"""
backend/services/transaction.py

Core logic for BitcoinTX with a hybrid double-entry system:
 - Single-entry inputs (type, amount, from_account, to_account, etc.)
 - Multi-line LedgerEntry creation for same-currency double-entry
 - Cross-currency Buy/Sell skip net-zero checks for simpler personal ledgers
 - BTC FIFO logic for sells/withdrawals
 - Transfer logic that handles partial-lot fee disposal

Implementation Notes:
 - "Scorched Earth": after editing or deleting a transaction, we remove
   all ledger entries and re-lot everything in strict chronological order.
   This is acceptable for a single-user system with a relatively small dataset.
 - If we backdate (change the timestamp to earlier), we run a partial re-lot
   from that timestamp forward, then also do the "scorched earth" re-lot to
   ensure consistency.

No references to Ghostscript remain. This file remains compatible
with your new pdftk-based system for filling/flattening IRS forms.
"""

import logging
import requests
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_DOWN
from typing import Optional
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models.transaction import (Transaction, LedgerEntry, BitcoinLot, LotDisposal)
from backend.models.account import Account
from backend.schemas.transaction import TransactionCreate

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------
# Public Functions (CRUD + retrieval)
# ------------------------------------------------------------------------------
def get_all_transactions(db: Session):
    """
    Return all Transactions, typically ordered descending by timestamp.
    """
    return (
        db.query(Transaction)
        .order_by(Transaction.timestamp.desc())
        .all()
    )


def get_transaction_by_id(db: Session, transaction_id: int):
    """
    Retrieve a single Transaction by its ID (returns None if not found).
    """
    return db.query(Transaction).filter(Transaction.id == transaction_id).first()


def create_transaction_record(tx_data: dict, db: Session) -> Transaction:
    """
    Creates a new Transaction in the hybrid multi-line ledger system.

    Steps:
      1) Ensure "BTC Fees" account exists.
      2) Validate transaction type usage.
      3) Validate fee usage for transaction type.
      4) Create Transaction row in DB.
      5) Convert single-entry fields => multiple ledger lines.
      6) Possibly skip net-zero check if cross-currency (Buy/Sell).
      7) If Deposit/Buy => create BTC lot if to_acct=BTC
      8) If Withdrawal/Sell => do FIFO disposal if from_acct=BTC
      9) If disposal => compute realized gains summary
    """
    # 1) Ensure BTC Fees account
    ensure_fee_account_exists(db)

    # 2 & 3) Validate transaction type and fee rules
    _enforce_transaction_type_rules(tx_data, db)
    _enforce_fee_rules(tx_data, db)

    # 4) Insert Transaction
    now_utc = datetime.now(timezone.utc)
    new_tx = Transaction(
        from_account_id=tx_data.get("from_account_id"),
        to_account_id=tx_data.get("to_account_id"),
        type=tx_data.get("type"),
        amount=tx_data.get("amount"),
        fee_amount=tx_data.get("fee_amount"),
        fee_currency=tx_data.get("fee_currency"),
        timestamp=tx_data.get("timestamp", now_utc),
        source=tx_data.get("source"),
        purpose=tx_data.get("purpose"),
        cost_basis_usd=tx_data.get("cost_basis_usd"),
        proceeds_usd=tx_data.get("proceeds_usd"),
        is_locked=tx_data.get("is_locked", False),
        created_at=now_utc,
        updated_at=now_utc
    )
    db.add(new_tx)
    db.flush()  # new_tx.id is now available

    # Optional grouping usage
    new_tx.group_id = new_tx.id

    # 5) Build ledger lines
    remove_ledger_entries_for_tx(new_tx, db)
    build_ledger_entries_for_transaction(new_tx, tx_data, db)

    # 6) Possibly skip net-zero if cross-currency
    _maybe_verify_balance_for_internal(new_tx, db)

    # 7-9) Partial-lot logic
    if new_tx.type in ("Deposit", "Buy"):
        maybe_create_bitcoin_lot(new_tx, tx_data, db)
    elif new_tx.type in ("Withdrawal", "Sell"):
        maybe_dispose_lots_fifo(new_tx, tx_data, db)
        compute_sell_summary_from_disposals(new_tx, db)
    elif new_tx.type == "Transfer":
        from_acct = db.query(Account).get(new_tx.from_account_id)
        # If from_acct is BTC, ensure fee_amount/currency are set
        if from_acct and from_acct.currency == "BTC":
            if new_tx.fee_amount is None or new_tx.fee_amount <= 0:
                logger.warning(f"Transfer {new_tx.id} missing fee_amount; defaulting to 0")
                new_tx.fee_amount = Decimal("0")
            if not new_tx.fee_currency:
                new_tx.fee_currency = "BTC"
        maybe_transfer_bitcoin_lot(new_tx, tx_data, db)

    # If disposal => finalize realized gain summary
    if new_tx.type in ("Sell", "Withdrawal"):
        compute_sell_summary_from_disposals(new_tx, db)

    db.commit()
    db.refresh(new_tx)
    return new_tx


def update_transaction_record(transaction_id: int, tx_data: dict, db: Session):
    """
    Update an existing Transaction if not locked.

    Steps:
      1) If locked => return None
      2) Re-validate usage & fee rules if relevant fields changed
      3) Overwrite transaction fields
      4) Rebuild ledger lines & partial-lot usage
      5) Possibly do partial-lot re-lot if backdated
      6) Finally do "scorched earth" re-lot of everything
    """
    tx = get_transaction_by_id(db, transaction_id)
    if not tx or tx.is_locked:
        return None

    old_timestamp = tx.timestamp

    # Step 2) Re-validate usage & fee rules if certain fields changed
    if any(k in tx_data for k in ("type", "from_account_id", "to_account_id")):
        _enforce_transaction_type_rules(tx_data, db)
    if any(k in tx_data for k in ("fee_amount", "fee_currency", "type")):
        _enforce_fee_rules(tx_data, db)

    # Step 3) Overwrite relevant fields
    if "from_account_id" in tx_data:
        tx.from_account_id = tx_data["from_account_id"]
    if "to_account_id" in tx_data:
        tx.to_account_id = tx_data["to_account_id"]
    if "amount" in tx_data:
        tx.amount = tx_data["amount"]
    if "fee_amount" in tx_data:
        tx.fee_amount = tx_data["fee_amount"]
    if "fee_currency" in tx_data:
        tx.fee_currency = tx_data["fee_currency"]
    if "type" in tx_data:
        tx.type = tx_data["type"]
    if "timestamp" in tx_data:
        tx.timestamp = tx_data["timestamp"]
    if "source" in tx_data:
        tx.source = tx_data["source"]
    if "purpose" in tx_data:
        tx.purpose = tx_data["purpose"]
    if "cost_basis_usd" in tx_data:
        tx.cost_basis_usd = tx_data["cost_basis_usd"]
    if "proceeds_usd" in tx_data:
        tx.proceeds_usd = tx_data["proceeds_usd"]

    tx.updated_at = datetime.now(timezone.utc)

    # Remove existing ledger entries & partial-lot usage
    remove_ledger_entries_for_tx(tx, db)
    remove_lot_usage_for_tx(tx, db)

    # Rebuild ledger lines
    build_ledger_entries_for_transaction(tx, tx_data, db)
    _maybe_verify_balance_for_internal(tx, db)

    # Partial-lot logic
    if tx.type in ("Deposit", "Buy"):
        maybe_create_bitcoin_lot(tx, tx_data, db)
    elif tx.type == "Transfer":
        maybe_transfer_bitcoin_lot(tx, tx_data, db)
    elif tx.type in ("Sell", "Withdrawal"):
        maybe_dispose_lots_fifo(tx, tx_data, db)
        compute_sell_summary_from_disposals(tx, db)

    # Step 5) Check for backdating
    new_timestamp = tx.timestamp
    earliest_timestamp = min(old_timestamp, new_timestamp)
    if new_timestamp < old_timestamp:
        logger.info(
            f"[Backdating Detected] Tx {tx.id} from {old_timestamp} => {new_timestamp}. "
            f"Re-lot from earliest={earliest_timestamp}"
        )
        recalculate_subsequent_transactions(db, earliest_timestamp)
    else:
        logger.info(
            f"[Timestamp Forward/Unchanged] Tx {tx.id} from {old_timestamp} => {new_timestamp}. "
            "(No partial-lot re-lot needed unless desired.)"
        )

    # Step 6) "Scorched Earth" to ensure final re-lot
    recalculate_all_transactions(db)

    db.commit()
    db.refresh(tx)
    return tx


def delete_transaction_record(transaction_id: int, db: Session):
    """
    Delete a transaction if not locked.
    Removes ledger entries, partial-lot usage, and re-lots everything.
    """
    tx = get_transaction_by_id(db, transaction_id)
    if not tx or tx.is_locked:
        return False

    db.delete(tx)
    db.commit()

    recalculate_all_transactions(db)
    return True


# ------------------------------------------------------------------------------
# Internal Helpers
# ------------------------------------------------------------------------------
def ensure_fee_account_exists(db: Session):
    """
    If 'BTC Fees' doesn't exist, create it.
    This prevents referencing a non-existent account in fee lines.
    """
    fee_acct = db.query(Account).filter_by(name="BTC Fees").first()
    if not fee_acct:
        fee_acct = Account(user_id=1, name="BTC Fees", currency="BTC")
        db.add(fee_acct)
        db.commit()
        db.refresh(fee_acct)
    return fee_acct


def remove_ledger_entries_for_tx(tx: Transaction, db: Session):
    """
    Remove all LedgerEntries associated with the given transaction.
    """
    for entry in list(tx.ledger_entries):
        db.delete(entry)
    db.flush()


def remove_lot_usage_for_tx(tx: Transaction, db: Session):
    """
    Remove partial-lot disposals & newly created lots for the transaction.
    """
    for disp in list(tx.lot_disposals):
        db.delete(disp)
    for lot in list(tx.bitcoin_lots_created):
        db.delete(lot)
    db.flush()


def build_ledger_entries_for_transaction(tx: Transaction, tx_data: dict, db: Session):
    """
    Convert single-entry data => multi-line ledger.
    Handles cross-currency Buy/Sell logic, Transfer fees, etc.
    """
    from_acct_id = tx_data.get("from_account_id")
    to_acct_id = tx_data.get("to_account_id")
    tx_type = tx_data.get("type", "")
    amount = Decimal(tx_data.get("amount", 0))
    fee_amount = Decimal(tx_data.get("fee_amount", 0))
    fee_currency = (tx_data.get("fee_currency") or "BTC").upper()

    # If user provided None or empty proceeds_usd, treat it as "0"
    proceeds_raw = tx_data.get("proceeds_usd") or "0"
    proceeds_usd = Decimal(proceeds_raw)

    from_acct = db.query(Account).get(from_acct_id) if from_acct_id else None
    to_acct = db.query(Account).get(to_acct_id) if to_acct_id else None

    # -------------------------------------------------------------------------
    # 1) Transfer with BTC fee
    # -------------------------------------------------------------------------
    if (
        tx_type == "Transfer"
        and from_acct
        and from_acct.currency == "BTC"
        and fee_amount > 0
    ):
        # Debit from_acct
        db.add(LedgerEntry(
            transaction_id=tx.id,
            account_id=from_acct.id,
            amount=-amount,
            currency=from_acct.currency,
            entry_type="MAIN_OUT"
        ))
        # Credit to_acct minus fee
        if to_acct and amount > 0:
            net_in = amount - fee_amount
            db.add(LedgerEntry(
                transaction_id=tx.id,
                account_id=to_acct.id,
                amount=net_in if net_in > 0 else Decimal("0"),
                currency=to_acct.currency,
                entry_type="MAIN_IN"
            ))
        fee_acct = db.query(Account).filter_by(name="BTC Fees").first()
        if fee_acct:
            db.add(LedgerEntry(
                transaction_id=tx.id,
                account_id=fee_acct.id,
                amount=fee_amount,
                currency="BTC",
                entry_type="FEE"
            ))
        db.flush()
        return

    # -------------------------------------------------------------------------
    # 2) Sell => from BTC => to USD
    # -------------------------------------------------------------------------
    if (
        tx_type == "Sell"
        and from_acct and from_acct.currency == "BTC"
        and to_acct and to_acct.currency == "USD"
    ):
        # Subtract BTC
        if amount > 0:
            db.add(LedgerEntry(
                transaction_id=tx.id,
                account_id=from_acct.id,
                amount=-amount,
                currency="BTC",
                entry_type="MAIN_OUT"
            ))

        # Subtract fee if fee_currency = USD
        net_usd_in = proceeds_usd
        if fee_currency == "USD":
            net_usd_in = proceeds_usd - fee_amount
            if net_usd_in < 0:
                net_usd_in = Decimal("0")

        # Overwrite with new net proceeds in the tx_data
        tx_data["proceeds_usd"] = str(net_usd_in)

        # Credit to_acct with net_usd_in
        if net_usd_in > 0:
            db.add(LedgerEntry(
                transaction_id=tx.id,
                account_id=to_acct.id,
                amount=net_usd_in,
                currency="USD",
                entry_type="MAIN_IN"
            ))
        # Fee line to "USD Fees"
        if fee_amount > 0 and fee_currency == "USD":
            fee_acct = db.query(Account).filter_by(name="USD Fees").first()
            if fee_acct:
                db.add(LedgerEntry(
                    transaction_id=tx.id,
                    account_id=fee_acct.id,
                    amount=fee_amount,
                    currency="USD",
                    entry_type="FEE"
                ))
        db.flush()
        return

    # -------------------------------------------------------------------------
    # 3) Buy => from USD => to BTC
    # -------------------------------------------------------------------------
    if (
        tx_type == "Buy"
        and from_acct and from_acct.currency == "USD"
        and to_acct and to_acct.currency == "BTC"
    ):
        amount_btc = Decimal(tx_data.get("amount", "0"))
        fee_amt = Decimal(tx_data.get("fee_amount", "0"))
        cost_basis_usd = Decimal(tx_data.get("cost_basis_usd", "0"))

        total_usd_out = cost_basis_usd + fee_amt
        db.add(LedgerEntry(
            transaction_id=tx.id,
            account_id=from_acct.id,
            amount=-total_usd_out,
            currency="USD",
            entry_type="MAIN_OUT"
        ))
        if amount_btc > 0:
            db.add(LedgerEntry(
                transaction_id=tx.id,
                account_id=to_acct.id,
                amount=amount_btc,
                currency="BTC",
                entry_type="MAIN_IN"
            ))
        if fee_amt > 0 and fee_currency == "USD":
            fee_acct = db.query(Account).filter_by(name="USD Fees").first()
            if fee_acct:
                db.add(LedgerEntry(
                    transaction_id=tx.id,
                    account_id=fee_acct.id,
                    amount=fee_amt,
                    currency="USD",
                    entry_type="FEE"
                ))
        db.flush()
        return

    # -------------------------------------------------------------------------
    # 4) Fallback: Deposits, Withdrawals, or other
    # -------------------------------------------------------------------------
    if from_acct and amount > 0:
        main_out_amt = -(amount + fee_amount)
        db.add(LedgerEntry(
            transaction_id=tx.id,
            account_id=from_acct.id,
            amount=main_out_amt,
            currency=from_acct.currency,
            entry_type="MAIN_OUT"
        ))
    if to_acct and amount > 0:
        db.add(LedgerEntry(
            transaction_id=tx.id,
            account_id=to_acct.id,
            amount=amount,
            currency=to_acct.currency,
            entry_type="MAIN_IN"
        ))
    if fee_amount > 0:
        # Fee to either BTC Fees or USD Fees
        if fee_currency == "BTC":
            fee_acct = db.query(Account).filter_by(name="BTC Fees").first()
        else:
            fee_acct = db.query(Account).filter_by(name="USD Fees").first()
        if fee_acct:
            db.add(LedgerEntry(
                transaction_id=tx.id,
                account_id=fee_acct.id,
                amount=fee_amount,
                currency=fee_currency,
                entry_type="FEE"
            ))
    db.flush()


def maybe_create_bitcoin_lot(tx: Transaction, tx_data: dict, db: Session):
    """
    If Deposit/Buy => create a new BitcoinLot if 'to_acct' is BTC.
    If fee is USD for a Buy, add it to cost basis automatically.
    """
    to_acct = db.query(Account).get(tx.to_account_id)
    if not to_acct or to_acct.currency != "BTC":
        return

    btc_amount = tx.amount or Decimal("0")
    if btc_amount <= 0:
        return

    cost_basis = Decimal(tx_data.get("cost_basis_usd", "0"))
    fee_cur = (tx_data.get("fee_currency") or "").upper()
    fee_amt = Decimal(tx_data.get("fee_amount", "0"))

    # If it's a Buy w/ USD fee, add that fee to cost basis
    if tx.type == "Buy" and fee_cur == "USD":
        cost_basis += fee_amt

    new_lot = BitcoinLot(
        created_txn_id=tx.id,
        acquired_date=tx.timestamp,
        total_btc=btc_amount,
        remaining_btc=btc_amount,
        cost_basis_usd=cost_basis,
    )
    db.add(new_lot)
    db.flush()


def maybe_dispose_lots_fifo(tx: Transaction, tx_data: dict, db: Session):
    """
    For a Sell/Withdrawal from a BTC account, do FIFO disposal of partial lots.
    - If purpose=Gift/Donation/Lost => forced proceeds=0
    - If purpose=Spent => user-supplied proceeds + BTC fee offset
    - Otherwise, if proceeds_usd is None or invalid, default to 0
    """
    from_acct = db.query(Account).get(tx.from_account_id)
    if not from_acct or from_acct.currency != "BTC":
        return

    btc_outflow = float(tx.amount or 0)
    if btc_outflow <= 0:
        return

    # 1) Safely parse proceeds. Default to 0 if None/invalid
    raw_proceeds = tx_data.get("proceeds_usd")
    if raw_proceeds is None:
        raw_proceeds = "0"
    try:
        total_proceeds = float(raw_proceeds)
    except (ValueError, TypeError):
        total_proceeds = 0.0

    # 2) Check purpose for forced 0 or "Spent" logic
    purpose_lower = (tx.purpose or "").lower()
    if tx.type == "Withdrawal" and purpose_lower in ("gift", "donation", "lost"):
        total_proceeds = 0.0
    elif tx.type == "Withdrawal" and purpose_lower == "spent":
        fee_btc = float(tx.fee_amount or 0)
        fee_cur = (tx.fee_currency or "").upper()
        if fee_btc > 0 and fee_cur == "BTC" and btc_outflow > 0 and total_proceeds > 0:
            implied_price = total_proceeds / btc_outflow
            fee_in_usd = fee_btc * implied_price
            net_proceeds = total_proceeds - fee_in_usd
            if net_proceeds < 0:
                net_proceeds = 0.0
            total_proceeds = net_proceeds

    # 3) FIFO disposal across lots
    lots = (
        db.query(BitcoinLot)
        .filter(BitcoinLot.remaining_btc > 0)
        .order_by(BitcoinLot.acquired_date.asc())
        .all()
    )
    remaining_outflow = btc_outflow
    total_outflow = btc_outflow

    for lot in lots:
        if remaining_outflow <= 0:
            break
        if lot.remaining_btc <= 0:
            continue

        can_use = min(float(lot.remaining_btc), remaining_outflow)
        cost_per_btc = (
            Decimal(lot.cost_basis_usd) / Decimal(lot.total_btc)
            if lot.total_btc
            else Decimal("0")
        )
        disposal_basis = (cost_per_btc * Decimal(can_use)).quantize(Decimal("0.01"), rounding=ROUND_HALF_DOWN)

        partial_proceeds = Decimal("0")
        if total_outflow > 0:
            ratio = Decimal(can_use) / Decimal(total_outflow)
            partial_proceeds = (ratio * Decimal(total_proceeds)).quantize(Decimal("0.01"), rounding=ROUND_HALF_DOWN)

        disposal_gain = partial_proceeds - disposal_basis
        # If Gift/Donation/Lost => override gain to 0
        if tx.type == "Withdrawal" and purpose_lower in ("gift", "donation", "lost"):
            disposal_gain = Decimal("0.0")

        # Determine holding period
        acquired_date = lot.acquired_date
        if acquired_date.tzinfo is None:
            acquired_date = acquired_date.replace(tzinfo=timezone.utc)
        days_held = (tx.timestamp - acquired_date).days
        hp = "LONG" if days_held >= 365 else "SHORT"

        disp = LotDisposal(
            lot_id=lot.id,
            transaction_id=tx.id,
            disposed_btc=Decimal(can_use),
            disposal_basis_usd=disposal_basis,
            proceeds_usd_for_that_portion=partial_proceeds,
            realized_gain_usd=disposal_gain,
            holding_period=hp
        )
        db.add(disp)

        lot.remaining_btc -= Decimal(can_use)
        remaining_outflow -= can_use

    db.flush()


def compute_sell_summary_from_disposals(tx: Transaction, db: Session):
    """
    Summarize partial-lot disposals (Sell/Withdrawal). Overwrite
    tx.cost_basis_usd, tx.proceeds_usd, tx.realized_gain_usd, holding_period
    based on the earliest acquisition date among those partial-lot disposals.
    """
    disposals = db.query(LotDisposal).filter(LotDisposal.transaction_id == tx.id).all()
    if not disposals:
        return

    total_basis = Decimal("0.0")
    total_gain = Decimal("0.0")
    total_proceeds = Decimal("0.0")
    earliest_date = None

    for disp in disposals:
        total_basis += (disp.disposal_basis_usd or Decimal("0"))
        total_gain += (disp.realized_gain_usd or Decimal("0"))
        total_proceeds += (disp.proceeds_usd_for_that_portion or Decimal("0"))

        lot = db.query(BitcoinLot).get(disp.lot_id)
        if lot and (earliest_date is None or lot.acquired_date < earliest_date):
            earliest_date = lot.acquired_date

    tx.cost_basis_usd = total_basis
    tx.realized_gain_usd = total_gain

    if total_proceeds > 0:
        tx.proceeds_usd = total_proceeds

    if earliest_date:
        if earliest_date.tzinfo is None:
            earliest_date = earliest_date.replace(tzinfo=timezone.utc)
        days_held = (tx.timestamp - earliest_date).days
        tx.holding_period = "LONG" if days_held >= 365 else "SHORT"
    else:
        tx.holding_period = None

    db.flush()


def get_btc_price(timestamp: datetime, db: Session) -> Decimal:
    """
    Fetch the historical BTC price in USD at the given timestamp from /api/bitcoin/price/history.
    If that fails, fallback to live price.
    """
    try:
        timestamp_str = timestamp.strftime("%Y-%m-%d")
        response = requests.get(
            "http://localhost:8000/api/bitcoin/price/history",
            params={"date": timestamp_str}
        )
        response.raise_for_status()
        price_data = response.json()
        if "USD" not in price_data:
            raise ValueError("USD price not found in response")
        return Decimal(str(price_data["USD"]))
    except (requests.RequestException, ValueError, KeyError) as e:
        # Attempt fallback to live
        try:
            live_resp = requests.get("http://localhost:8000/api/bitcoin/price")
            live_resp.raise_for_status()
            live_price_data = live_resp.json()
            if "USD" in live_price_data:
                return Decimal(str(live_price_data["USD"]))
        except (requests.RequestException, ValueError, KeyError):
            raise HTTPException(
                status_code=500,
                detail=f"Failed to fetch BTC price: {str(e)}"
            )


def maybe_transfer_bitcoin_lot(tx: Transaction, tx_data: dict, db: Session):
    """
    Splits source lots for an internal BTC transfer from one BTC account to another,
    disposing the fee portion and carrying forward the remainder as a new partial-lot.
    """
    from_acct = db.query(Account).get(tx.from_account_id)
    to_acct = db.query(Account).get(tx.to_account_id)
    if not from_acct or not to_acct:
        return
    if from_acct.currency != "BTC" or to_acct.currency != "BTC":
        return

    btc_outflow = Decimal(tx.amount or 0)
    fee_btc = Decimal(tx.fee_amount or 0) if (tx.fee_currency or "").upper() == "BTC" else Decimal("0")
    total_outflow = btc_outflow + fee_btc
    if total_outflow <= 0:
        return

    # Gather lots from 'from_acct' in FIFO
    lots = (
        db.query(BitcoinLot)
        .join(Transaction, Transaction.id == BitcoinLot.created_txn_id)
        .filter(
            BitcoinLot.remaining_btc > 0,
            Transaction.to_account_id == tx.from_account_id
        )
        .order_by(BitcoinLot.acquired_date.asc())
        .all()
    )

    remaining_outflow = total_outflow
    remaining_fee = fee_btc
    transfers_for_destination = []

    for lot in lots:
        if remaining_outflow <= 0:
            break
        if lot.remaining_btc <= 0:
            continue

        btc_to_use = min(lot.remaining_btc, remaining_outflow)
        cost_per_btc = (
            lot.cost_basis_usd / lot.total_btc if lot.total_btc > 0 else Decimal("0")
        )
        cost_portion = (cost_per_btc * btc_to_use).quantize(Decimal("0.01"), rounding=ROUND_HALF_DOWN)

        lot.remaining_btc -= btc_to_use
        db.add(lot)
        remaining_outflow -= btc_to_use

        portion_for_fee = min(btc_to_use, remaining_fee)
        portion_for_dest = btc_to_use - portion_for_fee

        # Fee disposal
        if portion_for_fee > 0:
            disposal_basis = (cost_per_btc * portion_for_fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_DOWN)
            btc_unit_price = get_btc_price(tx.timestamp, db)
            proceeds_for_fee = (btc_unit_price * portion_for_fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_DOWN)
            realized_gain = proceeds_for_fee - disposal_basis

            acquired_date = lot.acquired_date
            if acquired_date.tzinfo is None:
                acquired_date = acquired_date.replace(tzinfo=timezone.utc)
            days_held = (tx.timestamp - acquired_date).days
            hp = "LONG" if days_held >= 365 else "SHORT"

            disp = LotDisposal(
                lot_id=lot.id,
                transaction_id=tx.id,
                disposed_btc=portion_for_fee,
                disposal_basis_usd=disposal_basis,
                proceeds_usd_for_that_portion=proceeds_for_fee,
                realized_gain_usd=realized_gain,
                holding_period=hp
            )
            db.add(disp)
            remaining_fee -= portion_for_fee

        # Destination partial-lot
        if portion_for_dest > 0:
            transfers_for_destination.append((lot, portion_for_dest, cost_per_btc, lot.acquired_date))

    if remaining_fee > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough BTC to cover fee {fee_btc}"
        )
    if remaining_outflow > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough BTC to transfer {btc_outflow} + fee {fee_btc}"
        )

    # Create partial-lot(s) in the destination
    for (orig_lot, amt_btc, cost_per_btc, acquired_date) in transfers_for_destination:
        if acquired_date.tzinfo is None:
            acquired_date = acquired_date.replace(tzinfo=timezone.utc)
        cost_portion = (cost_per_btc * amt_btc).quantize(Decimal("0.01"), rounding=ROUND_HALF_DOWN)
        new_lot = BitcoinLot(
            created_txn_id=tx.id,
            acquired_date=acquired_date,
            total_btc=amt_btc,
            remaining_btc=amt_btc,
            cost_basis_usd=cost_portion
        )
        db.add(new_lot)

    db.flush()


def recalculate_all_transactions(db: Session):
    """
    "Scorched Earth": remove all ledger lines, partial-lot disposals,
    and BitcoinLots. Then re-lot everything in chronological order.
    """
    db.query(LedgerEntry).delete()
    db.query(LotDisposal).delete()
    db.query(BitcoinLot).delete()
    db.flush()

    all_txs = (
        db.query(Transaction)
        .order_by(Transaction.timestamp.asc(), Transaction.id.asc())
        .all()
    )
    for rec_tx in all_txs:
        sub_tx_data = {
            "from_account_id": rec_tx.from_account_id,
            "to_account_id": rec_tx.to_account_id,
            "type": rec_tx.type,
            "amount": rec_tx.amount,
            "fee_amount": rec_tx.fee_amount,
            "fee_currency": rec_tx.fee_currency,
            "cost_basis_usd": rec_tx.cost_basis_usd,
            "proceeds_usd": rec_tx.proceeds_usd,
            "timestamp": rec_tx.timestamp,
            "source": rec_tx.source,
            "purpose": rec_tx.purpose,
        }
        build_ledger_entries_for_transaction(rec_tx, sub_tx_data, db)
        _maybe_verify_balance_for_internal(rec_tx, db)

        if rec_tx.type in ("Deposit", "Buy"):
            maybe_create_bitcoin_lot(rec_tx, sub_tx_data, db)
        elif rec_tx.type in ("Sell", "Withdrawal"):
            maybe_dispose_lots_fifo(rec_tx, sub_tx_data, db)
            compute_sell_summary_from_disposals(rec_tx, db)
        elif rec_tx.type == "Transfer":
            maybe_transfer_bitcoin_lot(rec_tx, sub_tx_data, db)

    db.flush()


def recalculate_subsequent_transactions(db: Session, from_timestamp: datetime):
    """
    Partial-lot re-lot for transactions >= from_timestamp, more efficient
    than "scorched earth" for large datasets.
    """
    logger.info(f"[Partial Re-Lot] Starting from {from_timestamp.isoformat()}")

    affected_txs = (
        db.query(Transaction)
        .filter(Transaction.timestamp >= from_timestamp)
        .order_by(Transaction.timestamp.asc(), Transaction.id.asc())
        .all()
    )
    tx_ids = [t.id for t in affected_txs]

    db.query(LedgerEntry).filter(LedgerEntry.transaction_id.in_(tx_ids)).delete(synchronize_session=False)
    db.query(LotDisposal).filter(LotDisposal.transaction_id.in_(tx_ids)).delete(synchronize_session=False)
    db.query(BitcoinLot).filter(BitcoinLot.created_txn_id.in_(tx_ids)).delete(synchronize_session=False)
    db.flush()

    for rec_tx in affected_txs:
        sub_tx_data = {
            "from_account_id": rec_tx.from_account_id,
            "to_account_id": rec_tx.to_account_id,
            "type": rec_tx.type,
            "amount": rec_tx.amount,
            "fee_amount": rec_tx.fee_amount,
            "fee_currency": rec_tx.fee_currency,
            "cost_basis_usd": rec_tx.cost_basis_usd,
            "proceeds_usd": rec_tx.proceeds_usd,
            "timestamp": rec_tx.timestamp,
            "source": rec_tx.source,
            "purpose": rec_tx.purpose,
        }
        build_ledger_entries_for_transaction(rec_tx, sub_tx_data, db)
        _maybe_verify_balance_for_internal(rec_tx, db)

        if rec_tx.type in ("Deposit", "Buy"):
            maybe_create_bitcoin_lot(rec_tx, sub_tx_data, db)
        elif rec_tx.type in ("Sell", "Withdrawal"):
            maybe_dispose_lots_fifo(rec_tx, sub_tx_data, db)
            compute_sell_summary_from_disposals(rec_tx, db)
        elif rec_tx.type == "Transfer":
            maybe_transfer_bitcoin_lot(rec_tx, sub_tx_data, db)

    db.flush()
    logger.info("[Partial Re-Lot] Completed partial-lot recalculation.")


# --------------------------------------------------------------------------------
# Double-Entry (with Cross-Currency Skip) & Fee Rules
# --------------------------------------------------------------------------------
def _maybe_verify_balance_for_internal(tx: Transaction, db: Session):
    """
    If type=Buy or Sell => skip net-zero check (cross-currency).
    Otherwise, enforce net=0 for internal transactions (not external=99).
    """
    if tx.type in ("Buy", "Sell"):
        return
    _verify_double_entry_balance_for_internal(tx, db)


def _verify_double_entry_balance_for_internal(tx: Transaction, db: Session):
    """
    Ensure that ledger entries net to 0 by currency for internal transactions.
    Skip checks if from=99 or to=99 (external).
    """
    if tx.from_account_id == 99 or tx.to_account_id == 99:
        return

    entries = db.query(LedgerEntry).filter(LedgerEntry.transaction_id == tx.id).all()
    sums_by_currency = defaultdict(Decimal)
    for entry in entries:
        if entry.account_id != 99:
            sums_by_currency[entry.currency] += entry.amount

    for currency, total in sums_by_currency.items():
        if total != Decimal("0"):
            raise HTTPException(
                status_code=400,
                detail=f"Ledger not balanced for {currency}: {total}"
            )


def _enforce_fee_rules(tx_data: dict, db: Session):
    """
    Validate fee usage by transaction type:
      - Transfer => fee must match from_acct currency
      - Buy/Sell => fee must be USD
      - Deposit/Withdrawal => no special fee rule
    """
    tx_type = tx_data.get("type")
    from_id = tx_data.get("from_account_id")
    fee_amt = Decimal(tx_data.get("fee_amount", 0))
    fee_cur = (tx_data.get("fee_currency") or "USD").upper()

    # If there's no fee, skip checks
    if fee_amt <= 0:
        return

    if tx_type == "Transfer":
        if not from_id or from_id == 99:
            return
        from_acct = db.query(Account).get(from_id)
        if from_acct and from_acct.currency == "BTC" and fee_cur != "BTC":
            raise HTTPException(
                status_code=400,
                detail="Transfer from BTC => fee must be BTC."
            )
        if from_acct and from_acct.currency == "USD" and fee_cur != "USD":
            raise HTTPException(
                status_code=400,
                detail="Transfer from USD => fee must be USD."
            )

    elif tx_type in ("Buy", "Sell"):
        if fee_cur != "USD":
            raise HTTPException(
                status_code=400,
                detail=f"{tx_type} => fee must be USD."
            )


def _enforce_transaction_type_rules(tx_data: dict, db: Session):
    """
    Enforce correct usage of from/to for each transaction type:
      - Deposit => from=99 => to=internal
      - Withdrawal => from=internal => to=99
      - Transfer => from/to internal & same currency
      - Buy => from=3 => to=4
      - Sell => from=4 => to=3
      - Otherwise => error
    """
    tx_type = tx_data.get("type")
    from_id = tx_data.get("from_account_id")
    to_id = tx_data.get("to_account_id")

    if tx_type == "Deposit":
        if from_id != 99:
            raise HTTPException(400, "Deposit => from=99 (external).")
        if not to_id or to_id == 99:
            raise HTTPException(400, "Deposit => to=internal account.")

    elif tx_type == "Withdrawal":
        if to_id != 99:
            raise HTTPException(400, "Withdrawal => to=99 (external).")
        if not from_id or from_id == 99:
            raise HTTPException(400, "Withdrawal => from=internal.")

    elif tx_type == "Transfer":
        if not from_id or from_id == 99 or not to_id or to_id == 99:
            raise HTTPException(400, "Transfer => both from/to must be internal.")
        db_from = db.query(Account).get(from_id)
        db_to = db.query(Account).get(to_id)
        if db_from and db_to and db_from.currency != db_to.currency:
            raise HTTPException(400, "Transfer => same currency required.")

    elif tx_type == "Buy":
        if from_id != 3:
            raise HTTPException(400, "Buy => from=3 (Exchange USD).")
        if to_id != 4:
            raise HTTPException(400, "Buy => to=4 (Exchange BTC).")

    elif tx_type == "Sell":
        if from_id != 4:
            raise HTTPException(400, "Sell => from=4 (Exchange BTC).")
        if to_id != 3:
            raise HTTPException(400, "Sell => to=3 (Exchange USD).")

    else:
        raise HTTPException(400, f"Unknown transaction type: {tx_type}")


def delete_all_transactions(db: Session) -> int:
    """
    Bulk cleanup: remove all transactions (and references).
    Return how many were deleted.
    """
    all_txs = db.query(Transaction).all()
    count = len(all_txs)
    for tx in all_txs:
        db.delete(tx)
    db.commit()
    return count