"""Merge PM custom equipment and document download request migrations.

Revision ID: 20260922_merge_pm_docs
Revises: 20260922_pm_equipment_optional, 74e7373bcc01
"""

revision = "20260922_merge_pm_docs"
down_revision = ("20260922_pm_equipment_optional", "74e7373bcc01")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
