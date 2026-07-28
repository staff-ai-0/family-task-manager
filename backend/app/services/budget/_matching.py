"""One definition of "the same amount" for the budget domain.

Two services answer "is this a duplicate transaction?" — DuplicateGuardService
(scan-time, warns before creating) and DeduplicateService (batch, merges after
the fact). Each carried its own AMOUNT_TOLERANCE and its own inline window
arithmetic, so tuning one silently gave the two flows different definitions of
identical. Keeping the constant here makes that impossible.
"""

# 1% of the larger amount. Wide enough for tip/rounding differences between a
# bank alert and a receipt scan of the same purchase.
AMOUNT_TOLERANCE = 0.01


def amount_tolerance_cents(amount_cents: int, pct: float = AMOUNT_TOLERANCE) -> int:
    """Half-width of the match window around ``amount_cents``.

    No minimum floor. A ``max(1, ...)`` floor forced a 1-cent window onto
    amounts where a true 1% rounds to zero, which made a zero-amount row a
    "duplicate" of a real 1-cent transaction and destroyed it.
    """
    return int(abs(amount_cents) * pct)


def within_tolerance(a_cents: int, b_cents: int, pct: float = AMOUNT_TOLERANCE) -> bool:
    """Symmetric amount match.

    Scaled by the LARGER magnitude so the answer cannot depend on which row is
    examined first — an order-dependent window let the same pair be duplicates
    or not depending on insertion order.
    """
    scale = max(abs(a_cents), abs(b_cents))
    return abs(a_cents - b_cents) <= amount_tolerance_cents(scale, pct)
