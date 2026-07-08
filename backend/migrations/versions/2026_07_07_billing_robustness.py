"""billing robustness: staged checkout columns + review flag on family_subscriptions

- pending_plan_id / pending_billing_cycle / pending_paypal_subscription_id:
  a checkout started by a family that already has a live subscription is
  staged here instead of clobbering the live row; /activate promotes on
  payment confirmation.
- needs_review / review_reason: conservative marker set by refund/reversal
  webhook events for operator follow-up (no automatic downgrade).

Revision ID: billing_robustness
Revises: reward_redemptions
Create Date: 2026-07-07

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'billing_robustness'
down_revision = 'reward_redemptions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'family_subscriptions',
        sa.Column(
            'pending_plan_id', UUID(as_uuid=True),
            sa.ForeignKey('subscription_plans.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.add_column(
        'family_subscriptions',
        sa.Column('pending_billing_cycle', sa.String(length=20), nullable=True),
    )
    op.add_column(
        'family_subscriptions',
        sa.Column('pending_paypal_subscription_id', sa.String(length=100), nullable=True),
    )
    op.add_column(
        'family_subscriptions',
        sa.Column(
            'needs_review', sa.Boolean(), nullable=False, server_default='false'
        ),
    )
    op.add_column(
        'family_subscriptions',
        sa.Column('review_reason', sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('family_subscriptions', 'review_reason')
    op.drop_column('family_subscriptions', 'needs_review')
    op.drop_column('family_subscriptions', 'pending_paypal_subscription_id')
    op.drop_column('family_subscriptions', 'pending_billing_cycle')
    op.drop_column('family_subscriptions', 'pending_plan_id')
