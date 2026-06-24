"""TokenService — mint/resolve/revoke per-family MCP bearer tokens.

Tokens are minted with format ``mcp_<32 hex chars>``.
Only the SHA-256 hex digest is persisted; the plaintext is returned once at
mint time.  ``resolve`` updates ``last_used_at`` on each valid use.
"""

import hashlib
import secrets
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.jarvis_mcp_token import JarvisMcpToken


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class TokenService:
    @staticmethod
    async def mint(
        db: AsyncSession,
        family_id: UUID,
        user_id: UUID,
        label: str,
    ) -> tuple["JarvisMcpToken", str]:
        """Create a new token.  Returns (row, plaintext_secret)."""
        secret = "mcp_" + secrets.token_hex(16)  # 4 + 32 chars = 36 total
        token_hash = _hash(secret)
        token_prefix = secret[:8]
        row = JarvisMcpToken(
            family_id=family_id,
            created_by=user_id,
            label=label,
            token_hash=token_hash,
            token_prefix=token_prefix,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row, secret

    @staticmethod
    async def resolve(
        db: AsyncSession,
        secret: str,
    ) -> "JarvisMcpToken | None":
        """Look up a token by its plaintext secret.

        Returns None if the token does not exist or has been revoked.
        Updates ``last_used_at`` on a valid hit.
        """
        token_hash = _hash(secret)
        result = await db.execute(
            select(JarvisMcpToken).where(
                JarvisMcpToken.token_hash == token_hash,
                JarvisMcpToken.revoked_at.is_(None),
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        # Update last_used_at without loading the full ORM object again.
        await db.execute(
            update(JarvisMcpToken)
            .where(JarvisMcpToken.id == row.id)
            .values(last_used_at=datetime.now(timezone.utc))
        )
        await db.commit()
        await db.refresh(row)
        return row

    @staticmethod
    async def revoke(
        db: AsyncSession,
        token_id: UUID,
        family_id: UUID,
    ) -> None:
        """Revoke a token.  Silently ignores tokens that don't belong to the family."""
        await db.execute(
            update(JarvisMcpToken)
            .where(
                JarvisMcpToken.id == token_id,
                JarvisMcpToken.family_id == family_id,
                JarvisMcpToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc))
        )
        await db.commit()
