"""Pay the week from a bank-transfer receipt: scanner parsing, kid + week
mapping, the confirm endpoint (receipt amount is the paycheck), folio dedupe."""
import json
from datetime import date
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.exceptions import ValidationError
from app.models.cash_transaction import CashTransaction, CashTransactionType
from app.models.payout_receipt import PayoutReceipt
from app.services.bank_service import BankService
from app.services.name_match import Member
from app.services.payout_receipt_scanner_service import parse_receipt, week_numbers_from_concept
from app.services.payout_receipt_service import iso_week_monday, match_beneficiary, split_amount

PNG = b"\x89PNG\r\n\x1a\n" + b"fake"
SCAN = "/api/bank/payout-receipts/scan"
CONFIRM = "/api/bank/payout-receipts/confirm"

# The seven real slips the parent uploaded (Aug–Sep 2026).
SLIPS = [
    ("0011968514", "2026-09-04", "semana 36", 250.0),
    ("0086401124", "2026-09-22", "semana", 250.0),
    ("0090172139", "2026-09-14", "semana 36 y 37", 500.0),
    ("0018523252", "2026-08-26", "Transf a Ariana Mich", 250.0),
    ("0020165571", "2026-08-16", "semana y oxxo", 430.0),
    ("0029882120", "2026-08-11", "semana", 295.0),
]


# ── pure ────────────────────────────────────────────────────────────────────

class TestParse:
    @pytest.mark.parametrize("folio,day,concept,amount", SLIPS)
    def test_real_slips(self, folio, day, concept, amount):
        r = parse_receipt(json.dumps({
            "folio": folio, "date": day, "concept": concept, "amount": amount,
            "beneficiary": "Ariana Michelle M", "dest_last4": "9737", "confidence": 0.95,
        }))
        assert r.readable and r.folio == folio          # leading zeros survive
        assert r.amount_cents == int(amount * 100)
        assert r.dest_last4 == "9737" and r.receipt_date == date.fromisoformat(day)

    def test_amount_formats(self):
        for raw in ("$ 250.00", "1,250.50", 250, "250"):
            assert parse_receipt(json.dumps({"folio": "1", "amount": raw})).amount_cents in (25000, 125050)

    @pytest.mark.parametrize("bad", [None, 0, -5, "abc", True, 10**9])
    def test_bad_amount_is_unreadable(self, bad):
        assert not parse_receipt(json.dumps({"folio": "1", "amount": bad})).readable

    def test_no_folio_is_unreadable(self):
        assert not parse_receipt(json.dumps({"folio": None, "amount": 250})).readable

    def test_garbage_raises(self):
        with pytest.raises(ValidationError):
            parse_receipt("no json here")


class TestWeeks:
    @pytest.mark.parametrize("concept,expected", [
        ("semana 36", [36]), ("semana 36 y 37", [36, 37]), ("Semanas 36, 37 y 38", [36, 37, 38]),
        ("semana 36-38", [36, 37, 38]), ("semana y oxxo", []), ("semana", []),
        ("Transf a Ariana Mich", []), ("semana 99", []), ("", []),
    ])
    def test_concept(self, concept, expected):
        assert week_numbers_from_concept(concept) == expected

    def test_iso_week_monday(self):
        assert iso_week_monday(36, date(2026, 9, 4)) == date(2026, 8, 31)
        # Early-January slip naming week 52 means the previous year's.
        assert iso_week_monday(52, date(2027, 1, 4)) == date(2026, 12, 21)

    def test_split_keeps_every_centavo(self):
        assert split_amount(50000, 2) == [25000, 25000]
        assert sum(split_amount(10001, 3)) == 10001


class TestBeneficiary:
    M = [Member(uuid4(), "Ariana", "child"), Member(uuid4(), "Lucas", "teen")]

    def test_full_bank_name_matches_short_member_name(self):
        assert match_beneficiary("Ariana Michelle M", self.M) == self.M[0].id

    def test_no_match_and_empty(self):
        assert match_beneficiary("Pedro Perez", self.M) is None
        assert match_beneficiary("", self.M) is None

    def test_specific_name_wins_but_a_tie_matches_nobody(self):
        ana, ana_sofia = Member(uuid4(), "Ana", "child"), Member(uuid4(), "Ana Sofia", "child")
        assert match_beneficiary("Ana Sofia Lopez", [ana, ana_sofia]) == ana_sofia.id
        assert match_beneficiary("Ana Lopez", [ana, Member(uuid4(), "Ana", "teen")]) is None


# ── api ─────────────────────────────────────────────────────────────────────

def _vision(payload):
    patcher = patch("app.core.llm.OpenAI")
    mock_openai = patcher.start()
    msg = MagicMock(); msg.content = json.dumps(payload)
    choice = MagicMock(); choice.message = msg; choice.finish_reason = "stop"
    completion = MagicMock(); completion.choices = [choice]
    client = MagicMock(); client.chat.completions.create.return_value = completion
    mock_openai.return_value = client
    return patcher


async def _kid_on_chore_mode(db, kid, cap=25000):
    acct = await BankService.ensure_account(db, kid)
    acct.allowance_mode = "chore_proportional"
    acct.allowance_cents = cap
    await db.commit()


async def _week(db, family_id, back=1):
    from conftest import current_week_monday
    from datetime import timedelta
    return (await current_week_monday(db, family_id)) - timedelta(weeks=back)


async def _balance(db, kid):
    await db.refresh(kid)
    return kid.cash_cents


class TestScan:
    async def test_free_family_gets_upgrade_required(self, client, auth_headers):
        r = await client.post(SCAN, files=[("files", ("a.png", PNG, "image/png"))], headers=auth_headers)
        assert r.status_code == 403

    async def test_proposal_matches_kid_and_stores_nothing(
        self, client, db_session, auth_headers, plus_subscription, test_family, test_child_user, monkeypatch,
    ):
        from app.core import config
        monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
        await _kid_on_chore_mode(db_session, test_child_user)
        patcher = _vision({"folio": "0011968514", "date": "2026-09-04", "concept": "semana", "amount": 250,
                           "beneficiary": "Test Child Z", "dest_last4": "9737", "confidence": 0.9})
        try:
            r = await client.post(SCAN, files=[("files", ("a.png", PNG, "image/png"))], headers=auth_headers)
        finally:
            patcher.stop()
        assert r.status_code == 200, r.text
        row = r.json()["receipts"][0]
        assert row["readable"] and row["user_id"] == str(test_child_user.id)
        assert row["folio"] == "0011968514" and row["amount_cents"] == 25000
        assert row["allocations"] and sum(a["amount_cents"] for a in row["allocations"]) == 25000
        assert (await db_session.execute(select(func.count()).select_from(PayoutReceipt))).scalar() == 0

    async def test_one_bad_file_does_not_fail_the_batch(
        self, client, auth_headers, plus_subscription, monkeypatch,
    ):
        from app.core import config
        monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
        patcher = _vision({"folio": None, "amount": None})
        try:
            r = await client.post(SCAN, files=[
                ("files", ("a.png", PNG, "image/png")), ("files", ("b.txt", b"hello world", "text/plain")),
            ], headers=auth_headers)
        finally:
            patcher.stop()
        assert r.status_code == 200
        rows = r.json()["receipts"]
        assert [x["readable"] for x in rows] == [False, False] and rows[1]["error"]

    async def test_too_many_files(self, client, auth_headers, plus_subscription):
        r = await client.post(SCAN, files=[("files", (f"{i}.png", PNG, "image/png")) for i in range(11)], headers=auth_headers)
        assert r.status_code == 413


class TestConfirm:
    def _body(self, kid, week, amount=25000, folio="0011968514", **kw):
        return {"folio": folio, "user_id": str(kid.id), "amount_cents": amount, "concept": "semana",
                "allocations": [{"week_of": week.isoformat(), "amount_cents": amount}], **kw}

    async def test_receipt_amount_is_the_paycheck(
        self, client, db_session, auth_headers, plus_subscription, test_family, test_child_user,
    ):
        await _kid_on_chore_mode(db_session, test_child_user)
        week = await _week(db_session, test_family.id)
        r = await client.post(CONFIRM, json=self._body(test_child_user, week), headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["weeks"][0]["top_up"] is False
        # Credited exactly the receipt (not the chore math) AND paid out: the
        # transfer already left the account, so nothing is left "owed".
        assert await _balance(db_session, test_child_user) == 0
        payouts = (await db_session.execute(select(CashTransaction).where(
            CashTransaction.user_id == test_child_user.id, CashTransaction.type == CashTransactionType.PAYOUT,
        ))).scalars().all()
        assert [p.amount_cents for p in payouts] == [-25000] and "0011968514" in (payouts[0].description or "")
        rows = (await db_session.execute(select(CashTransaction).where(
            CashTransaction.user_id == test_child_user.id, CashTransaction.type == CashTransactionType.ALLOWANCE,
        ))).scalars().all()
        assert rows and sum(t.amount_cents for t in rows) == 25000 and all(t.week_of == week for t in rows)
        assert any("0011968514" in (t.description or "") for t in rows)
        assert (await db_session.execute(select(func.count()).select_from(PayoutReceipt))).scalar() == 1

    async def test_same_folio_never_pays_twice(
        self, client, db_session, auth_headers, plus_subscription, test_family, test_child_user,
    ):
        await _kid_on_chore_mode(db_session, test_child_user)
        week = await _week(db_session, test_family.id)
        assert (await client.post(CONFIRM, json=self._body(test_child_user, week), headers=auth_headers)).status_code == 200
        other = await _week(db_session, test_family.id, back=2)
        r = await client.post(CONFIRM, json=self._body(test_child_user, other), headers=auth_headers)
        assert r.status_code == 409
        payouts = (await db_session.execute(select(func.count()).select_from(CashTransaction).where(
            CashTransaction.user_id == test_child_user.id, CashTransaction.type == CashTransactionType.PAYOUT))).scalar()
        assert payouts == 1 and await _balance(db_session, test_child_user) == 0

    async def test_two_weeks_in_one_receipt(
        self, client, db_session, auth_headers, plus_subscription, test_family, test_child_user,
    ):
        await _kid_on_chore_mode(db_session, test_child_user)
        w1, w2 = await _week(db_session, test_family.id, 2), await _week(db_session, test_family.id, 1)
        body = {"folio": "0090172139", "user_id": str(test_child_user.id), "amount_cents": 50000,
                "allocations": [{"week_of": w1.isoformat(), "amount_cents": 25000},
                                {"week_of": w2.isoformat(), "amount_cents": 25000}]}
        r = await client.post(CONFIRM, json=body, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert await _balance(db_session, test_child_user) == 0     # 2 weeks credited and paid out
        credited = (await db_session.execute(select(func.coalesce(func.sum(CashTransaction.amount_cents), 0)).where(
            CashTransaction.user_id == test_child_user.id, CashTransaction.type == CashTransactionType.ALLOWANCE))).scalar()
        assert int(credited) == 50000

    async def test_already_paid_week_is_topped_up_not_blocked(
        self, client, db_session, auth_headers, plus_subscription, test_family, test_child_user, test_parent_user,
    ):
        await _kid_on_chore_mode(db_session, test_child_user)
        week = await _week(db_session, test_family.id)
        await BankService.release_chore_paycheck(
            db_session, test_child_user, test_family.id, week, entitled=True, adjustment_cents=10000,
            released_by=test_parent_user.id,
        )
        before = await _balance(db_session, test_child_user)
        r = await client.post(CONFIRM, json=self._body(test_child_user, week, amount=5000, folio="0000000001"), headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["weeks"][0]["top_up"] is True
        assert await _balance(db_session, test_child_user) == before   # extra credited and paid out

    async def test_a_save_share_split_does_not_leave_money_owed(
        self, client, db_session, auth_headers, plus_subscription, test_family, test_child_user,
    ):
        # A kid with auto-split on must still net to zero: the receipt credit is
        # 100% spend (the money already left the account), so the payout settles it.
        await _kid_on_chore_mode(db_session, test_child_user)
        acct = await BankService.ensure_account(db_session, test_child_user)
        acct.split_spend_pct, acct.split_save_pct, acct.split_share_pct = 50, 30, 20
        await db_session.commit()
        week = await _week(db_session, test_family.id)
        r = await client.post(CONFIRM, json=self._body(test_child_user, week), headers=auth_headers)
        assert r.status_code == 200, r.text
        assert await _balance(db_session, test_child_user) == 0
        await db_session.refresh(acct)
        assert (acct.spend_cents, acct.save_cents, acct.share_cents) == (0, 0, 0)

    async def test_allocations_must_add_up(
        self, client, db_session, auth_headers, plus_subscription, test_family, test_child_user,
    ):
        await _kid_on_chore_mode(db_session, test_child_user)
        week = await _week(db_session, test_family.id)
        body = self._body(test_child_user, week)
        body["allocations"][0]["amount_cents"] = 100
        assert (await client.post(CONFIRM, json=body, headers=auth_headers)).status_code == 422
        assert await _balance(db_session, test_child_user) == 0

    async def test_future_week_rejected(
        self, client, db_session, auth_headers, plus_subscription, test_family, test_child_user,
    ):
        await _kid_on_chore_mode(db_session, test_child_user)
        week = await _week(db_session, test_family.id, back=-2)
        assert (await client.post(CONFIRM, json=self._body(test_child_user, week), headers=auth_headers)).status_code == 422

    async def test_kid_not_on_chore_mode_rejected(
        self, client, db_session, auth_headers, plus_subscription, test_family, test_child_user,
    ):
        week = await _week(db_session, test_family.id)
        r = await client.post(CONFIRM, json=self._body(test_child_user, week), headers=auth_headers)
        assert r.status_code == 422
        assert (await db_session.execute(select(func.count()).select_from(PayoutReceipt))).scalar() == 0

    async def test_other_family_kid_is_not_found(
        self, client, db_session, auth_headers, plus_subscription, test_family,
    ):
        from app.models.family import Family
        from app.models.user import APPROVAL_APPROVED, User, UserRole
        fam2 = Family(name="Other", timezone="UTC"); db_session.add(fam2); await db_session.commit()
        stranger = User(email=f"s{uuid4().hex[:8]}@t.com", name="Stranger", role=UserRole.CHILD, family_id=fam2.id,
                        email_verified=True, cash_cents=0, points=0, approval_status=APPROVAL_APPROVED, is_active=True)
        db_session.add(stranger); await db_session.commit()
        week = await _week(db_session, test_family.id)
        r = await client.post(CONFIRM, json=self._body(stranger, week), headers=auth_headers)
        assert r.status_code in (403, 404)

    async def test_free_family_cannot_confirm(
        self, client, db_session, auth_headers, test_family, test_child_user,
    ):
        await _kid_on_chore_mode(db_session, test_child_user)
        week = await _week(db_session, test_family.id)
        assert (await client.post(CONFIRM, json=self._body(test_child_user, week), headers=auth_headers)).status_code == 403
