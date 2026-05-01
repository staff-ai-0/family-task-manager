"""
File Import Service for Budget Transactions

Handles parsing and importing OFX, QIF, and CAMT.053 files containing financial transactions.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from app.models.budget import BudgetTransaction, BudgetPayee
from app.services.budget.transaction_service import TransactionService
from app.services.budget.categorization_rule_service import CategorizationRuleService
from app.schemas.budget import TransactionCreate


@dataclass
class ImportedTransaction:
    date: date
    amount: int  # in cents
    payee_name: str
    notes: str = ""
    imported_id: str = ""


def detect_format(filename: str, content: bytes) -> str:
    """Detect file format based on extension and content sniffing.

    Returns "ofx", "qif", "camt", or "csv".
    """
    lower = filename.lower()
    if lower.endswith(".ofx") or lower.endswith(".qfx"):
        return "ofx"
    if lower.endswith(".qif"):
        return "qif"
    if lower.endswith(".xml"):
        return "camt"

    # Content sniffing as fallback
    text_start = content[:500].decode("utf-8", errors="ignore").strip()
    if "<OFX>" in text_start.upper() or "OFXHEADER" in text_start.upper():
        return "ofx"
    if text_start.startswith("!Type:") or text_start.startswith("!Account"):
        return "qif"
    if "camt.053" in text_start or "<Document" in text_start:
        return "camt"

    return "csv"


def parse_ofx(file_bytes: bytes) -> List[ImportedTransaction]:
    """Parse OFX/QFX files manually (SGML-like format).

    Key tags: <STMTTRN>, <DTPOSTED>, <TRNAMT>, <NAME>, <MEMO>, <FITID>.
    Amount in dollars -> convert to cents.
    Date format: YYYYMMDD or YYYYMMDDHHMMSS.
    """
    text = file_bytes.decode("utf-8", errors="replace")
    transactions: List[ImportedTransaction] = []

    # Split into transaction blocks
    trn_blocks = re.split(r"<STMTTRN>", text, flags=re.IGNORECASE)

    for block in trn_blocks[1:]:  # skip the first chunk before any <STMTTRN>
        # Trim at closing tag if present
        end_match = re.search(r"</STMTTRN>", block, flags=re.IGNORECASE)
        if end_match:
            block = block[:end_match.start()]

        dt_posted = _ofx_tag_value(block, "DTPOSTED")
        trn_amt = _ofx_tag_value(block, "TRNAMT")
        name = _ofx_tag_value(block, "NAME")
        memo = _ofx_tag_value(block, "MEMO")
        fitid = _ofx_tag_value(block, "FITID")

        if not dt_posted or not trn_amt:
            continue

        # Parse date
        txn_date = _parse_ofx_date(dt_posted)
        if not txn_date:
            continue

        # Parse amount (dollars -> cents)
        try:
            amount_cents = int(round(float(trn_amt) * 100))
        except (ValueError, TypeError):
            continue

        payee_name = (name or memo or "Unknown").strip()
        notes = memo.strip() if memo and memo != name else ""

        transactions.append(ImportedTransaction(
            date=txn_date,
            amount=amount_cents,
            payee_name=payee_name,
            notes=notes,
            imported_id=fitid.strip() if fitid else "",
        ))

    return transactions


def _ofx_tag_value(block: str, tag: str) -> Optional[str]:
    """Extract value for an OFX SGML tag (no closing tags in OFX 1.x)."""
    # Try self-closing XML style first: <TAG>value</TAG>
    pattern_xml = rf"<{tag}>\s*(.*?)\s*</{tag}>"
    m = re.search(pattern_xml, block, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()

    # OFX SGML style: <TAG>value\n
    pattern_sgml = rf"<{tag}>([^\r\n<]+)"
    m = re.search(pattern_sgml, block, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    return None


def _parse_ofx_date(date_str: str) -> Optional[date]:
    """Parse OFX date format: YYYYMMDD or YYYYMMDDHHMMSS[.XXX]."""
    date_str = date_str.strip()
    # Remove timezone info like [0:GMT]
    date_str = re.sub(r"\[.*?\]", "", date_str).strip()
    # Remove fractional seconds
    date_str = re.sub(r"\.\d+", "", date_str).strip()

    try:
        if len(date_str) >= 14:
            return datetime.strptime(date_str[:14], "%Y%m%d%H%M%S").date()
        elif len(date_str) >= 8:
            return datetime.strptime(date_str[:8], "%Y%m%d").date()
    except ValueError:
        pass
    return None


def parse_qif(file_bytes: bytes) -> List[ImportedTransaction]:
    """Parse QIF files (line-based format).

    D = date (M/D/Y or M/D'Y), T = amount, P = payee, M = memo, ^ = end of record.
    """
    text = file_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines()

    transactions: List[ImportedTransaction] = []
    current: dict = {}

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("!"):
            # Header line, skip
            continue

        code = line[0]
        value = line[1:].strip()

        if code == "D":
            current["date"] = _parse_qif_date(value)
        elif code == "T" or code == "U":
            current["amount"] = _parse_qif_amount(value)
        elif code == "P":
            current["payee"] = value
        elif code == "M":
            current["memo"] = value
        elif code == "N":
            current["number"] = value
        elif code == "^":
            # End of record
            txn_date = current.get("date")
            amount = current.get("amount")
            if txn_date is not None and amount is not None:
                payee = current.get("payee", "Unknown")
                memo = current.get("memo", "")
                number = current.get("number", "")
                transactions.append(ImportedTransaction(
                    date=txn_date,
                    amount=amount,
                    payee_name=payee,
                    notes=memo,
                    imported_id=number,
                ))
            current = {}

    return transactions


def _parse_qif_date(date_str: str) -> Optional[date]:
    """Parse QIF date formats: M/D/Y, M/D'Y, M-D-Y, M-D'Y."""
    date_str = date_str.strip()
    # Replace apostrophe year separator with /
    date_str = date_str.replace("'", "/")
    date_str = date_str.replace("-", "/")

    parts = date_str.split("/")
    if len(parts) != 3:
        return None

    try:
        month = int(parts[0])
        day = int(parts[1])
        year = int(parts[2])

        # Handle 2-digit year
        if year < 100:
            year += 2000 if year < 50 else 1900

        return date(year, month, day)
    except (ValueError, IndexError):
        return None


def _parse_qif_amount(amount_str: str) -> Optional[int]:
    """Parse QIF amount to cents."""
    amount_str = amount_str.strip().replace(",", "")
    try:
        return int(round(float(amount_str) * 100))
    except (ValueError, TypeError):
        return None


def parse_camt(file_bytes: bytes) -> List[ImportedTransaction]:
    """Parse CAMT.053 XML files.

    Namespace: urn:iso:std:iso:20022:tech:xsd:camt.053.001.02
    Entries: <Ntry> with <Amt>, <CdtDbtInd>, <BookgDt><Dt>, description in
    <NtryDtls><TxDtls><RmtInf><Ustrd>.
    """
    transactions: List[ImportedTransaction] = []

    try:
        root = ET.fromstring(file_bytes)
    except ET.ParseError:
        return transactions

    # Detect namespace
    ns = ""
    tag = root.tag
    if tag.startswith("{"):
        ns = tag[1:tag.index("}")]

    def _find(element, path):
        """Find element using namespace prefix."""
        if ns:
            parts = path.split("/")
            ns_path = "/".join(f"{{{ns}}}{p}" for p in parts)
            return element.find(ns_path)
        return element.find(path)

    def _findall(element, path):
        if ns:
            parts = path.split("/")
            ns_path = "/".join(f"{{{ns}}}{p}" for p in parts)
            return element.findall(ns_path)
        return element.findall(path)

    def _findtext(element, path, default=""):
        el = _find(element, path)
        return el.text.strip() if el is not None and el.text else default

    # Find all Ntry (entry) elements anywhere in the tree
    for ntry in root.iter(f"{{{ns}}}Ntry" if ns else "Ntry"):
        # Amount
        amt_el = _find(ntry, "Amt")
        if amt_el is None:
            continue
        try:
            amount_val = float(amt_el.text.strip())
        except (ValueError, TypeError, AttributeError):
            continue

        # Credit/Debit indicator
        cdt_dbt = _findtext(ntry, "CdtDbtInd", "DBIT")
        amount_cents = int(round(amount_val * 100))
        if cdt_dbt == "DBIT":
            amount_cents = -abs(amount_cents)
        else:
            amount_cents = abs(amount_cents)

        # Booking date
        dt_text = _findtext(ntry, "BookgDt/Dt")
        if not dt_text:
            dt_text = _findtext(ntry, "ValDt/Dt")
        if not dt_text:
            continue

        try:
            txn_date = date.fromisoformat(dt_text)
        except (ValueError, TypeError):
            continue

        # Description from remittance info
        description = _findtext(ntry, "NtryDtls/TxDtls/RmtInf/Ustrd")
        if not description:
            description = _findtext(ntry, "NtryDtls/TxDtls/AddtlTxInf")
        if not description:
            description = "CAMT Import"

        # Try to get account service reference as imported_id
        imported_id = _findtext(ntry, "NtryDtls/TxDtls/Refs/AcctSvcrRef")
        if not imported_id:
            imported_id = _findtext(ntry, "AcctSvcrRef")

        transactions.append(ImportedTransaction(
            date=txn_date,
            amount=amount_cents,
            payee_name=description,
            notes="",
            imported_id=imported_id,
        ))

    return transactions


async def import_file_transactions(
    db: AsyncSession,
    family_id: UUID,
    account_id: UUID,
    filename: str,
    file_bytes: bytes,
) -> dict:
    """Import transactions from a file (OFX/QIF/CAMT).

    Detects format, parses, creates transactions with auto-payee creation,
    rule application, and deduplication via imported_id.

    Returns:
        {"imported": int, "skipped": int, "errors": list}
    """
    fmt = detect_format(filename, file_bytes)

    if fmt == "ofx":
        parsed = parse_ofx(file_bytes)
    elif fmt == "qif":
        parsed = parse_qif(file_bytes)
    elif fmt == "camt":
        parsed = parse_camt(file_bytes)
    else:
        return {"imported": 0, "skipped": 0, "errors": ["Unsupported format. Use CSV import for CSV files."]}

    imported = 0
    skipped = 0
    errors: List[str] = []

    for txn in parsed:
        try:
            # Deduplication: skip if imported_id already exists for this account
            if txn.imported_id:
                stmt = select(BudgetTransaction).where(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.account_id == account_id,
                    BudgetTransaction.imported_id == txn.imported_id,
                    BudgetTransaction.deleted_at.is_(None),
                )
                result = await db.execute(stmt)
                if result.scalars().first():
                    skipped += 1
                    continue

            # Find or create payee
            payee_id = None
            if txn.payee_name:
                stmt = select(BudgetPayee).where(
                    BudgetPayee.family_id == family_id,
                    BudgetPayee.name == txn.payee_name,
                )
                payee_result = await db.execute(stmt)
                payee = payee_result.scalars().first()
                if payee:
                    payee_id = payee.id
                else:
                    new_payee = BudgetPayee(
                        family_id=family_id,
                        name=txn.payee_name,
                    )
                    db.add(new_payee)
                    await db.flush()
                    payee_id = new_payee.id

            # Auto-categorize
            category_id = await CategorizationRuleService.suggest_category(
                db, family_id,
                payee=txn.payee_name,
                description=txn.notes or None,
            )

            transaction_data = TransactionCreate(
                account_id=account_id,
                date=txn.date,
                amount=txn.amount,
                payee_id=payee_id,
                category_id=category_id,
                notes=txn.notes or None,
                imported_id=txn.imported_id or None,
                cleared=False,
                reconciled=False,
            )

            await TransactionService.create(db, family_id, transaction_data)
            imported += 1
        except Exception as e:
            errors.append(f"Row {txn.payee_name}/{txn.date}: {str(e)}")

    await db.commit()
    return {"imported": imported, "skipped": skipped, "errors": errors}
