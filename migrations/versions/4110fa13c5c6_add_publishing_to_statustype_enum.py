"""add_publishing_to_statustype_enum

Revision ID: 4110fa13c5c6
Revises: 56b9e73a218d
Create Date: 2026-10-24 13:28:52.665402

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '4110fa13c5c6'
down_revision: str | Sequence[str] | None = '56b9e73a218d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE statustype ADD VALUE IF NOT EXISTS 'PUBLISHING'")


def downgrade() -> None:
    """Downgrade schema."""
