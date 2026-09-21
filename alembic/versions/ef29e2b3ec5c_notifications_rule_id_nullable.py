"""notifications optional fields nullable

Revision ID: <auto>
Revises: <auto>
Create Date: <auto>
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'ef29e2b3ec5c'
down_revision = '20260920_field_work_progress'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for name, column_type in (
        ("rule_id", sa.UUID()),
        ("document_id", sa.UUID()),
        ("expiry_date", sa.Date()),
    ):
        op.alter_column(
            "notifications",
            name,
            existing_type=column_type,
            nullable=True,
        )


def downgrade() -> None:
    for name, column_type in (
        ("expiry_date", sa.Date()),
        ("document_id", sa.UUID()),
        ("rule_id", sa.UUID()),
    ):
        op.alter_column(
            "notifications",
            name,
            existing_type=column_type,
            nullable=False,
        )
