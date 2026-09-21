"""Add total_contract_value column to project_contracts table."""

import sqlalchemy as sa
from alembic import op

revision = "20260919_project_contract_value"
down_revision = "20260918_procurement_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = [c["name"] for c in insp.get_columns("project_contracts")]
    if "total_contract_value" not in cols:
        op.add_column(
            "project_contracts",
            sa.Column("total_contract_value", sa.Numeric(14, 2), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = [c["name"] for c in insp.get_columns("project_contracts")]
    if "total_contract_value" in cols:
        op.drop_column("project_contracts", "total_contract_value")
