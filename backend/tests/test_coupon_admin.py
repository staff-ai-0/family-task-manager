"""Operator coupon catalog.

coupons is cross-tenant by design — it is a catalog like subscription_plans,
not family data. Every route here must therefore be superadmin-only and
audited, and must never use verify_family_id / get_family_user.
"""
import pytest
from sqlalchemy import select

from app.models.operator_audit import OperatorAuditLog


@pytest.mark.asyncio
async def test_create_coupon(client, superadmin_headers):
    resp = await client.post(
        "/api/admin/coupons",
        headers=superadmin_headers,
        json={
            "code": "lanzamiento",
            "kind": "launch",
            "tier": "plus",
            "duration_days": 30,
            "max_redemptions": 500,
            "campaign": "Lanzamiento MX",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "LANZAMIENTO"  # normalized on write
    assert body["redemption_count"] == 0


@pytest.mark.asyncio
async def test_create_coupon_writes_an_audit_row(
    client, superadmin_headers, db_session
):
    await client.post(
        "/api/admin/coupons",
        headers=superadmin_headers,
        json={"code": "BETA2026", "kind": "beta", "tier": "pro",
              "duration_days": 180},
    )
    row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "coupon.create"
            )
        )
    ).scalars().first()
    assert row is not None
    assert row.params["code"] == "BETA2026"


@pytest.mark.asyncio
async def test_duplicate_code_is_rejected(client, superadmin_headers):
    payload = {"code": "UNICO", "kind": "launch", "tier": "plus",
               "duration_days": 30}
    first = await client.post(
        "/api/admin/coupons", headers=superadmin_headers, json=payload
    )
    assert first.status_code == 201
    second = await client.post(
        "/api/admin/coupons", headers=superadmin_headers, json=payload
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_create_coupon_rejects_bad_tier_and_bad_kind(
    client, superadmin_headers
):
    """Write-time validation. tier/kind are String(20) columns with NO CHECK
    constraint, and a bad tier row makes CouponService.redeem raise
    ValueError AFTER the cap bump — so the schema must refuse them at the
    door, not leave it to the redeem path to discover."""
    bad_tier = await client.post(
        "/api/admin/coupons", headers=superadmin_headers,
        json={"code": "MALTIER", "kind": "launch", "tier": "gold",
              "duration_days": 30},
    )
    assert bad_tier.status_code == 422
    bad_kind = await client.post(
        "/api/admin/coupons", headers=superadmin_headers,
        json={"code": "MALKIND", "kind": "promo", "tier": "plus",
              "duration_days": 30},
    )
    assert bad_kind.status_code == 422


@pytest.mark.asyncio
async def test_list_coupons(client, superadmin_headers):
    # The brief used code "UNO", but CreateCouponRequest (reviewed in Task 7)
    # requires >= 4 chars — the schema on disk wins.
    created = await client.post(
        "/api/admin/coupons", headers=superadmin_headers,
        json={"code": "SOLO", "kind": "launch", "tier": "plus",
              "duration_days": 30},
    )
    assert created.status_code == 201, created.text
    resp = await client.get("/api/admin/coupons", headers=superadmin_headers)
    assert resp.status_code == 200
    assert [c["code"] for c in resp.json()] == ["SOLO"]


@pytest.mark.asyncio
async def test_deactivate_a_coupon(client, superadmin_headers):
    created = await client.post(
        "/api/admin/coupons", headers=superadmin_headers,
        json={"code": "APAGAR", "kind": "launch", "tier": "plus",
              "duration_days": 30},
    )
    coupon_id = created.json()["id"]

    resp = await client.patch(
        f"/api/admin/coupons/{coupon_id}",
        headers=superadmin_headers,
        json={"is_active": False},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_immutable_fields_are_not_patchable(client, superadmin_headers):
    """tier/duration/code changes would retroactively alter what already
    issued grants meant — the schema must simply not accept them."""
    created = await client.post(
        "/api/admin/coupons", headers=superadmin_headers,
        json={"code": "FIJO", "kind": "launch", "tier": "plus",
              "duration_days": 30},
    )
    coupon_id = created.json()["id"]

    resp = await client.patch(
        f"/api/admin/coupons/{coupon_id}",
        headers=superadmin_headers,
        json={"tier": "pro", "duration_days": 3650},
    )
    assert resp.status_code == 200
    assert resp.json()["tier"] == "plus"
    assert resp.json()["duration_days"] == 30


@pytest.mark.asyncio
async def test_redemption_list_uses_the_authoritative_count(
    client, superadmin_headers, auth_headers, db_session
):
    created = await client.post(
        "/api/admin/coupons", headers=superadmin_headers,
        json={"code": "CONTAR", "kind": "launch", "tier": "plus",
              "duration_days": 30},
    )
    coupon_id = created.json()["id"]

    await client.post(
        "/api/subscriptions/coupons/redeem",
        headers=auth_headers,
        json={"code": "CONTAR"},
    )

    resp = await client.get(
        f"/api/admin/coupons/{coupon_id}/redemptions", headers=superadmin_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert len(body["redemptions"]) == 1
    assert body["redemptions"][0]["family_id"]


@pytest.mark.asyncio
async def test_revoke_a_grant(client, superadmin_headers, auth_headers, db_session):
    await client.post(
        "/api/admin/coupons", headers=superadmin_headers,
        json={"code": "REVOCAR", "kind": "comp", "tier": "pro",
              "duration_days": None},
    )
    redeemed = await client.post(
        "/api/subscriptions/coupons/redeem",
        headers=auth_headers,
        json={"code": "REVOCAR"},
    )
    grant_id = redeemed.json()["id"]

    resp = await client.post(
        f"/api/admin/credits/{grant_id}/revoke",
        headers=superadmin_headers,
        json={"reason": "granted by mistake"},
    )
    assert resp.status_code == 200

    after = await client.get("/api/subscriptions/credits", headers=auth_headers)
    assert after.json() == []


@pytest.mark.asyncio
async def test_revoke_is_not_repeatable_and_unknown_grant_is_404(
    client, superadmin_headers, auth_headers
):
    """Already-revoked → 409, nonexistent → 404 — never a 500. The audit
    trail should carry ONE revoke row per grant actually revoked."""
    await client.post(
        "/api/admin/coupons", headers=superadmin_headers,
        json={"code": "UNAVEZ", "kind": "comp", "tier": "plus",
              "duration_days": 30},
    )
    redeemed = await client.post(
        "/api/subscriptions/coupons/redeem",
        headers=auth_headers,
        json={"code": "UNAVEZ"},
    )
    grant_id = redeemed.json()["id"]

    first = await client.post(
        f"/api/admin/credits/{grant_id}/revoke",
        headers=superadmin_headers,
        json={"reason": "abuse"},
    )
    assert first.status_code == 200

    again = await client.post(
        f"/api/admin/credits/{grant_id}/revoke",
        headers=superadmin_headers,
        json={"reason": "abuse"},
    )
    assert again.status_code == 409

    missing = await client.post(
        "/api/admin/credits/00000000-0000-0000-0000-000000000000/revoke",
        headers=superadmin_headers,
        json={"reason": "typo"},
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("get", "/api/admin/coupons", None),
        ("post", "/api/admin/coupons",
         {"code": "NOPE", "kind": "launch", "tier": "plus", "duration_days": 30}),
    ],
)
async def test_coupon_routes_are_superadmin_only(
    client, auth_headers, method, path, payload
):
    call = getattr(client, method)
    resp = await call(path, headers=auth_headers, **({"json": payload} if payload else {}))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_id_bearing_coupon_routes_are_superadmin_only(
    client, superadmin_headers, auth_headers
):
    """PATCH / redemptions / revoke against REAL rows as a plain parent.

    Real ids on purpose: with a fabricated UUID a missing require_superadmin
    would still 404 from the service's own existence check and the test
    would pass vacuously. Against a live row, a dropped gate answers 200 —
    and the follow-up superadmin calls prove no write actually landed."""
    created = await client.post(
        "/api/admin/coupons", headers=superadmin_headers,
        json={"code": "GUARDIA", "kind": "launch", "tier": "plus",
              "duration_days": 30},
    )
    coupon_id = created.json()["id"]
    redeemed = await client.post(
        "/api/subscriptions/coupons/redeem",
        headers=auth_headers,
        json={"code": "GUARDIA"},
    )
    grant_id = redeemed.json()["id"]

    patched = await client.patch(
        f"/api/admin/coupons/{coupon_id}",
        headers=auth_headers,
        json={"is_active": False},
    )
    listed = await client.get(
        f"/api/admin/coupons/{coupon_id}/redemptions", headers=auth_headers
    )
    revoked = await client.post(
        f"/api/admin/credits/{grant_id}/revoke",
        headers=auth_headers,
        json={"reason": "not an operator"},
    )
    assert patched.status_code == 404
    assert listed.status_code == 404
    assert revoked.status_code == 404

    # Nothing landed: the coupon is still active and the grant still
    # revocable (a prior revoke would make this 409).
    rows = (await client.get(
        "/api/admin/coupons", headers=superadmin_headers
    )).json()
    guardia = next(r for r in rows if r["code"] == "GUARDIA")
    assert guardia["is_active"] is True
    real_revoke = await client.post(
        f"/api/admin/credits/{grant_id}/revoke",
        headers=superadmin_headers,
        json={"reason": "cleanup"},
    )
    assert real_revoke.status_code == 200


@pytest.mark.asyncio
async def test_patch_unknown_coupon_is_404(client, superadmin_headers):
    resp = await client.patch(
        "/api/admin/coupons/00000000-0000-0000-0000-000000000000",
        headers=superadmin_headers,
        json={"is_active": False},
    )
    assert resp.status_code == 404
