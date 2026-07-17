"""
Categorization Rule Service

Business logic for automatic transaction categorization based on payee/description patterns.
Supports multiple match types: exact, contains, startswith, regex.
"""

import re
from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.models.budget import BudgetCategorizationRule, BudgetCategory, BudgetTransaction
from app.schemas.budget import (
    CategorizationRuleCreate,
    CategorizationRuleUpdate,
)
from app.services.base_service import BaseFamilyService
from app.core.exceptions import NotFoundException, ValidationException


class CategorizationRuleService(BaseFamilyService[BudgetCategorizationRule]):
    """Service for categorization rule operations and pattern matching."""

    model = BudgetCategorizationRule

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        family_id: UUID,
        data: CategorizationRuleCreate,
    ) -> BudgetCategorizationRule:
        """
        Create a new categorization rule.

        Args:
            db: Database session
            family_id: Family ID
            data: Rule creation data

        Returns:
            Created categorization rule

        Raises:
            ValidationException: If rule_type or match_field is invalid
            NotFoundException: If category doesn't exist
        """
        # Validate rule_type
        valid_types = ["exact", "contains", "startswith", "regex"]
        if data.rule_type not in valid_types:
            raise ValidationException(
                f"Invalid rule_type '{data.rule_type}'. Must be one of: {', '.join(valid_types)}"
            )

        # Validate match_field
        valid_fields = ["payee", "description", "both"]
        if data.match_field not in valid_fields:
            raise ValidationException(
                f"Invalid match_field '{data.match_field}'. Must be one of: {', '.join(valid_fields)}"
            )

        # Validate regex pattern if applicable
        if data.rule_type == "regex":
            try:
                re.compile(data.pattern)
            except re.error as e:
                raise ValidationException(f"Invalid regex pattern: {str(e)}")

        # Verify category exists and belongs to family
        category = await db.scalar(
            select(BudgetCategory).where(
                and_(
                    BudgetCategory.id == data.category_id,
                    BudgetCategory.family_id == family_id,
                    BudgetCategory.deleted_at.is_(None),
                )
            )
        )
        if not category:
            raise NotFoundException("Category not found or does not belong to this family")

        # Serialize actions if present
        actions_data = None
        if hasattr(data, "actions") and data.actions is not None:
            actions_data = [a.model_dump() for a in data.actions]

        rule = BudgetCategorizationRule(
            family_id=family_id,
            category_id=data.category_id,
            rule_type=data.rule_type,
            match_field=data.match_field,
            pattern=data.pattern,
            enabled=data.enabled,
            priority=data.priority,
            notes=data.notes,
            actions=actions_data,
        )

        db.add(rule)
        await db.commit()
        await db.refresh(rule)
        return rule

    @classmethod
    async def update(
        cls,
        db: AsyncSession,
        rule_id: UUID,
        family_id: UUID,
        data: CategorizationRuleUpdate,
    ) -> BudgetCategorizationRule:
        """
        Update a categorization rule.

        Args:
            db: Database session
            rule_id: Rule ID to update
            family_id: Family ID for verification
            data: Update data

        Returns:
            Updated categorization rule

        Raises:
            ValidationException: If rule_type, match_field, or pattern is invalid
            NotFoundException: If rule or category doesn't exist
        """
        rule = await cls.get_by_id(db, rule_id, family_id)

        # Validate rule_type if provided
        if data.rule_type is not None:
            valid_types = ["exact", "contains", "startswith", "regex"]
            if data.rule_type not in valid_types:
                raise ValidationException(
                    f"Invalid rule_type '{data.rule_type}'. Must be one of: {', '.join(valid_types)}"
                )

        # Validate match_field if provided
        if data.match_field is not None:
            valid_fields = ["payee", "description", "both"]
            if data.match_field not in valid_fields:
                raise ValidationException(
                    f"Invalid match_field '{data.match_field}'. Must be one of: {', '.join(valid_fields)}"
                )

        # Validate regex pattern if provided
        if data.pattern is not None:
            rule_type = data.rule_type or rule.rule_type
            if rule_type == "regex":
                try:
                    re.compile(data.pattern)
                except re.error as e:
                    raise ValidationException(f"Invalid regex pattern: {str(e)}")

        # Verify category exists if provided
        if data.category_id is not None:
            category = await db.scalar(
                select(BudgetCategory).where(
                    and_(
                        BudgetCategory.id == data.category_id,
                        BudgetCategory.family_id == family_id,
                    )
                )
            )
            if not category:
                raise NotFoundException(
                    "Category not found or does not belong to this family"
                )

        # Only include non-None values in update
        update_data = data.model_dump(exclude_unset=True)
        # Serialize RuleAction objects to dicts for JSONB storage
        if "actions" in update_data and update_data["actions"] is not None:
            update_data["actions"] = [
                a if isinstance(a, dict) else a.model_dump()
                for a in update_data["actions"]
            ]
        return await cls.update_by_id(db, rule_id, family_id, update_data)

    @classmethod
    async def list_rules(
        cls,
        db: AsyncSession,
        family_id: UUID,
        enabled_only: bool = False,
    ) -> List[BudgetCategorizationRule]:
        """
        List all categorization rules for a family.

        Args:
            db: Database session
            family_id: Family ID
            enabled_only: If True, only return enabled rules

        Returns:
            List of categorization rules ordered by priority (descending) then created_at
        """
        query = select(BudgetCategorizationRule).where(
            BudgetCategorizationRule.family_id == family_id
        )

        if enabled_only:
            query = query.where(BudgetCategorizationRule.enabled == True)

        query = query.order_by(
            BudgetCategorizationRule.priority.desc(),
            BudgetCategorizationRule.created_at.asc(),
        )

        result = await db.execute(query)
        return result.scalars().all()

    @classmethod
    async def suggest_category(
        cls,
        db: AsyncSession,
        family_id: UUID,
        payee: Optional[str] = None,
        description: Optional[str] = None,
        item_name: Optional[str] = None,
    ) -> Optional[UUID]:
        """
        Suggest a category for a transaction based on payee/description/item_name and rules.

        Rules are evaluated in priority order (highest priority first).
        Returns the category_id from the first matching rule, or None if no match.

        The match field semantics:
          - rule.match_field == "payee"        → match against `payee`
          - rule.match_field == "description"  → match against `description`,
            falling back to `item_name` when description is None
          - rule.match_field == "both"         → match if payee OR description
            OR item_name matches

        `item_name` enables per-line categorization for receipt scans
        (e.g. a rule keyed on "leche" categorizes the milk line item even
        when the receipt's payee/description doesn't mention it).

        Args:
            db: Database session
            family_id: Family ID
            payee: Payee name (optional)
            description: Transaction description (optional)
            item_name: Single line-item name to match against
                description-pattern rules (optional)

        Returns:
            Suggested category_id or None if no rule matches
        """
        if not payee and not description and not item_name:
            return None

        # Get all enabled rules for this family, ordered by priority
        rules = await cls.list_rules(db, family_id, enabled_only=True)

        for rule in rules:
            if cls._match_rule(rule, payee, description, item_name):
                return rule.category_id

        return None

    @staticmethod
    def match_with_cached_rules(
        rules: list,
        *,
        payee: Optional[str] = None,
        description: Optional[str] = None,
        item_name: Optional[str] = None,
    ) -> Optional[UUID]:
        """In-memory match against an already-loaded rule list (no DB IO).

        Mirrors ``suggest_category`` but accepts a pre-loaded list of
        ``BudgetCategorizationRule`` rows. Callers that need to match many
        candidates (e.g. the receipt scanner running once per line item)
        should fetch the rule set once and reuse this method to avoid an
        N+1 SELECT on the rules table.

        Note: callers must respect the same ordering contract
        ``suggest_category`` relies on — load rules with
        ``list_rules(enabled_only=True)`` (priority DESC, created_at ASC)
        so the first match here is the highest-priority enabled rule.
        """
        if not payee and not description and not item_name:
            return None
        for rule in rules:
            if CategorizationRuleService._match_rule(rule, payee, description, item_name):
                return rule.category_id
        return None

    @classmethod
    async def apply_rule(
        cls,
        db: AsyncSession,
        transaction: BudgetTransaction,
        rule: BudgetCategorizationRule,
    ) -> BudgetTransaction:
        """
        Apply a rule's actions to a transaction.

        When the rule has no `actions` list, fall back to the legacy behavior
        of setting category_id from the rule.  When `actions` is populated,
        each action is applied in order.

        Returns the (modified but uncommitted) transaction.
        """
        if not rule.actions:
            # Legacy backward-compat: just set category
            transaction.category_id = rule.category_id
            return transaction

        for action in rule.actions:
            field = action.get("field")
            operation = action.get("operation", "set")
            value = action.get("value", "")

            if field == "category" and operation == "set":
                transaction.category_id = UUID(value) if value else None
            elif field == "payee" and operation == "set":
                transaction.payee_id = UUID(value) if value else None
            elif field == "notes":
                if operation == "set":
                    transaction.notes = value
                elif operation == "append":
                    transaction.notes = (transaction.notes or "") + value
                elif operation == "prepend":
                    transaction.notes = value + (transaction.notes or "")

        return transaction

    @staticmethod
    def _match_rule(
        rule: BudgetCategorizationRule,
        payee: Optional[str],
        description: Optional[str],
        item_name: Optional[str] = None,
    ) -> bool:
        """
        Check if a rule matches the given payee/description/item_name.

        Args:
            rule: The categorization rule
            payee: Payee name (optional)
            description: Transaction description (optional)
            item_name: Receipt line-item name (optional). Used as an
                additional source when match_field is 'description' or
                'both' — receipt scans don't have a free-form description
                column but each line item can drive categorization.

        Returns:
            True if the rule matches
        """
        if rule.match_field == "payee":
            return payee is not None and CategorizationRuleService._match_pattern(
                rule.pattern, payee, rule.rule_type
            )
        elif rule.match_field == "description":
            desc_match = description is not None and CategorizationRuleService._match_pattern(
                rule.pattern, description, rule.rule_type
            )
            item_match = item_name is not None and CategorizationRuleService._match_pattern(
                rule.pattern, item_name, rule.rule_type
            )
            return desc_match or item_match
        elif rule.match_field == "both":
            # For "both", match if payee OR description OR item_name matches
            payee_match = (
                payee is not None
                and CategorizationRuleService._match_pattern(
                    rule.pattern, payee, rule.rule_type
                )
            )
            description_match = (
                description is not None
                and CategorizationRuleService._match_pattern(
                    rule.pattern, description, rule.rule_type
                )
            )
            item_match = (
                item_name is not None
                and CategorizationRuleService._match_pattern(
                    rule.pattern, item_name, rule.rule_type
                )
            )
            return payee_match or description_match or item_match
        else:
            return False

    @staticmethod
    def _match_pattern(pattern: str, text: str, rule_type: str) -> bool:
        """
        Match a pattern against text based on rule type.

        All matching is case-insensitive.

        Args:
            pattern: The pattern to match
            text: The text to match against
            rule_type: Type of matching ('exact', 'contains', 'startswith', 'regex')

        Returns:
            True if pattern matches text
        """
        text_lower = text.lower()
        pattern_lower = pattern.lower()

        if rule_type == "exact":
            return text_lower == pattern_lower
        elif rule_type == "contains":
            return pattern_lower in text_lower
        elif rule_type == "startswith":
            return text_lower.startswith(pattern_lower)
        elif rule_type == "regex":
            try:
                return bool(re.search(pattern, text, re.IGNORECASE))
            except re.error:
                # Invalid regex should never happen (validated at creation/update)
                return False
        else:
            return False

    APPLY_ALL_BATCH_SIZE = 1000

    @classmethod
    async def apply_all_rules(
        cls,
        db: AsyncSession,
        family_id: UUID,
        max_transactions: int = 10000,
    ) -> dict:
        """Walk uncategorized transactions, apply matching rules. Returns {applied, skipped, scanned, truncated}.

        Processes up to `max_transactions` rows in batches of APPLY_ALL_BATCH_SIZE
        ordered by created_at desc. Skipped = uncategorized rows that did not match
        any rule. truncated=True when more uncategorized rows remain beyond the
        scan window after hitting max_transactions.
        """
        from app.models.budget import BudgetPayee

        rules = await cls.list_rules(db, family_id, enabled_only=True)

        applied = 0
        skipped = 0
        scanned = 0
        truncated = False

        # Each loop, applied rows leave the `category_id IS NULL` result set
        # after autoflush, so paginate by `skipped` (rows we passed over but
        # could not match) rather than total rows seen — otherwise we'd skip
        # past real candidates.
        while scanned < max_transactions:
            remaining = max_transactions - scanned
            batch_limit = min(cls.APPLY_ALL_BATCH_SIZE, remaining)
            txn_q = (
                select(BudgetTransaction, BudgetPayee.name)
                .outerjoin(BudgetPayee, BudgetTransaction.payee_id == BudgetPayee.id)
                .where(
                    and_(
                        BudgetTransaction.family_id == family_id,
                        BudgetTransaction.category_id.is_(None),
                        BudgetTransaction.deleted_at.is_(None),
                    )
                )
                .order_by(BudgetTransaction.created_at.desc())
                .limit(batch_limit)
                .offset(skipped)
            )
            rows = (await db.execute(txn_q)).all()
            if not rows:
                break

            for txn, payee_name in rows:
                matched_rule = None
                for rule in rules:
                    if cls._match_rule(rule, payee_name, txn.notes):
                        matched_rule = rule
                        break
                if matched_rule:
                    await cls.apply_rule(db, txn, matched_rule)
                    applied += 1
                else:
                    skipped += 1

            scanned += len(rows)
            if len(rows) < batch_limit:
                break

        if scanned >= max_transactions:
            # Total uncategorized = skipped (still in result set) + any rows
            # that remain beyond the scan window.
            tail_q = (
                select(func.count())
                .select_from(BudgetTransaction)
                .where(
                    and_(
                        BudgetTransaction.family_id == family_id,
                        BudgetTransaction.category_id.is_(None),
                        BudgetTransaction.deleted_at.is_(None),
                    )
                )
            )
            total = (await db.execute(tail_q)).scalar_one()
            truncated = total > skipped

        await db.commit()
        return {
            "applied": applied,
            "skipped": skipped,
            "scanned": scanned,
            "truncated": truncated,
        }

    @classmethod
    async def suggest_new_rules(
        cls,
        db: AsyncSession,
        family_id: UUID,
        min_count: int = 3,
    ) -> List[dict]:
        """Suggest payees with N+ uncategorized transactions and no existing exact rule.

        Returns list of {payee_id, payee_name, transaction_count}.
        """
        from sqlalchemy import func as sql_func
        from app.models.budget import BudgetPayee

        # Group uncategorized txns by payee
        agg_q = (
            select(
                BudgetPayee.id,
                BudgetPayee.name,
                sql_func.count(BudgetTransaction.id).label("cnt"),
            )
            .join(BudgetPayee, BudgetTransaction.payee_id == BudgetPayee.id)
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.category_id.is_(None),
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
            .group_by(BudgetPayee.id, BudgetPayee.name)
            .having(sql_func.count(BudgetTransaction.id) >= min_count)
        )
        rows = (await db.execute(agg_q)).all()

        # Existing exact rules on payee field — exclude those payee names
        rule_q = select(BudgetCategorizationRule.pattern).where(
            and_(
                BudgetCategorizationRule.family_id == family_id,
                BudgetCategorizationRule.rule_type == "exact",
                BudgetCategorizationRule.match_field == "payee",
            )
        )
        excluded = {p.lower() for p in (await db.execute(rule_q)).scalars().all()}

        return [
            {
                "payee_id": pid,
                "payee_name": pname,
                "transaction_count": cnt,
            }
            for pid, pname, cnt in rows
            if pname.lower() not in excluded
        ]

    # ------------------------------------------------------------------
    # Learning categorization (P2)
    # ------------------------------------------------------------------
    # Two complementary mechanisms, both derived from the family's own
    # categorized-transaction history — no new tables required:
    #
    #   (a) recent_payee_category_pairs / format_category_fewshot →
    #       few-shot context that primes the receipt-scanner vision prompt
    #       with "this family files HEB under Mandado" style hints so the
    #       model's category guess matches the household's established habits.
    #
    #   (b) suggest_rules_from_history → once a payee has been assigned the
    #       SAME category on N+ transactions (i.e. the user repeatedly makes
    #       the same correction), propose a durable BudgetCategorizationRule
    #       so the categorization becomes automatic going forward.
    # ------------------------------------------------------------------

    FEWSHOT_DEFAULT_LIMIT = 15

    @classmethod
    async def recent_payee_category_pairs(
        cls,
        db: AsyncSession,
        family_id: UUID,
        limit: int = FEWSHOT_DEFAULT_LIMIT,
    ) -> List[dict]:
        """Most-recently-used distinct (payee, category) pairs for a family.

        Returns ``[{"payee": str, "category": str}, ...]`` ordered most-recent
        first (by the latest ``updated_at`` of any transaction in the pair).
        Used to assemble few-shot context for the receipt-scanner prompt so
        the model inherits the household's established categorization habits.

        Family-scoped: only this family's categorized, non-deleted, non-split
        transactions contribute.
        """
        from app.models.budget import BudgetPayee

        q = (
            select(
                BudgetPayee.name,
                BudgetCategory.name,
                func.max(BudgetTransaction.updated_at).label("last_used"),
            )
            .join(BudgetPayee, BudgetTransaction.payee_id == BudgetPayee.id)
            .join(BudgetCategory, BudgetTransaction.category_id == BudgetCategory.id)
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.payee_id.isnot(None),
                    BudgetTransaction.category_id.isnot(None),
                    BudgetTransaction.deleted_at.is_(None),
                    BudgetTransaction.is_parent.is_(False),
                )
            )
            .group_by(BudgetPayee.name, BudgetCategory.name)
            .order_by(func.max(BudgetTransaction.updated_at).desc())
            .limit(limit)
        )
        rows = (await db.execute(q)).all()
        return [{"payee": payee_name, "category": cat_name} for payee_name, cat_name, _ in rows]

    @staticmethod
    def format_category_fewshot(pairs: List[dict]) -> str:
        """Render payee→category pairs as a prompt-ready hint block.

        Returns an empty string when there is no history, so callers can
        treat "no learned context" and "feature off" identically.
        """
        if not pairs:
            return ""
        lines = [
            "Known merchant→category history for this family "
            "(use as a hint when guessing the category):"
        ]
        for p in pairs:
            payee = (p.get("payee") or "").strip()
            category = (p.get("category") or "").strip()
            if payee and category:
                lines.append(f"- {payee} → {category}")
        # If every pair was blank we degrade to no hint rather than a header
        # with no examples.
        return "\n".join(lines) if len(lines) > 1 else ""

    @classmethod
    async def suggest_rules_from_history(
        cls,
        db: AsyncSession,
        family_id: UUID,
        min_count: int = 2,
    ) -> List[dict]:
        """Propose payee→category rules from repeated identical categorizations.

        For each payee whose transactions land in the SAME category at least
        ``min_count`` times (the dominant category is chosen when a payee spans
        several), and which has no existing exact payee rule, emit a suggestion:
        ``{payee_id, payee_name, category_id, category_name, match_count}``.

        This is the "learn from repeated corrections" half of P2 — after the
        parent recategorizes payee X → category Y a couple of times, we surface
        a one-click rule so it never needs correcting again. Family-scoped.
        """
        from app.models.budget import BudgetPayee

        agg_q = (
            select(
                BudgetPayee.id,
                BudgetPayee.name,
                BudgetCategory.id,
                BudgetCategory.name,
                func.count(BudgetTransaction.id).label("cnt"),
            )
            .join(BudgetPayee, BudgetTransaction.payee_id == BudgetPayee.id)
            .join(BudgetCategory, BudgetTransaction.category_id == BudgetCategory.id)
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.payee_id.isnot(None),
                    BudgetTransaction.category_id.isnot(None),
                    BudgetTransaction.deleted_at.is_(None),
                    BudgetTransaction.is_parent.is_(False),
                )
            )
            .group_by(
                BudgetPayee.id, BudgetPayee.name, BudgetCategory.id, BudgetCategory.name
            )
            .having(func.count(BudgetTransaction.id) >= min_count)
        )
        rows = (await db.execute(agg_q)).all()

        # Payees that already have an exact payee rule are already automated —
        # don't nag the user to create a rule they effectively have.
        rule_q = select(BudgetCategorizationRule.pattern).where(
            and_(
                BudgetCategorizationRule.family_id == family_id,
                BudgetCategorizationRule.rule_type == "exact",
                BudgetCategorizationRule.match_field == "payee",
            )
        )
        excluded = {p.lower() for p in (await db.execute(rule_q)).scalars().all()}

        # Collapse to one suggestion per payee — its dominant category.
        best: dict = {}
        for pid, pname, cid, cname, cnt in rows:
            if pname.lower() in excluded:
                continue
            current = best.get(pid)
            if (
                current is None
                or cnt > current["match_count"]
                or (cnt == current["match_count"] and cname < current["category_name"])
            ):
                best[pid] = {
                    "payee_id": pid,
                    "payee_name": pname,
                    "category_id": cid,
                    "category_name": cname,
                    "match_count": cnt,
                }

        suggestions = list(best.values())
        suggestions.sort(key=lambda r: r["match_count"], reverse=True)
        return suggestions
