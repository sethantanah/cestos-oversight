"""Reconcile equipment history constraints and independent document types.

Revision ID: 9979ee24a6d7
Revises: 0006_time_leave
"""

from alembic import op
import sqlalchemy as sa

revision = "9979ee24a6d7"
down_revision = "0006_time_leave"
branch_labels = None
depends_on = None

DOCUMENT_TYPES = "CV NATIONAL_ID PASSPORT DRIVERS_LICENSE WORK_PERMIT EMPLOYMENT_CONTRACT MEDICAL_CERTIFICATE SAFETY_CERTIFICATE TRAINING_CERTIFICATE EDUCATIONAL_CERTIFICATE TRADE_CERTIFICATE PROFESSIONAL_CERTIFICATE INSURANCE_DOCUMENT POLICE_CLEARANCE OTHER PURCHASE_DOCUMENT OWNERSHIP_DOCUMENT REGISTRATION INSURANCE WARRANTY INSPECTION_CERTIFICATE ROADWORTHINESS IMPORT_DOCUMENT MANUFACTURER_MANUAL SERVICE_MANUAL PARTS_MANUAL CALIBRATION_CERTIFICATE LEASE_AGREEMENT RENTAL_AGREEMENT PHOTO".split()


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    enum_additions = {
        "component_status": ["AVAILABLE", "UNDER_REPAIR", "SCRAPPED", "REPLACED"],
        "asset_status": ["ASSIGNED", "DEMOBILIZING", "QUARANTINED", "LOST", "STOLEN"],
        "ownership_type": ["THIRD_PARTY"],
        "meter_type": ["ODOMETER_MILES", "CYCLES"],
        "reading_type": ["ODOMETER_MILES", "CYCLES"],
    }
    for enum_name, labels in enum_additions.items():
        for label in labels:
            op.execute(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{label}'")
    indexes = {i["name"] for i in inspector.get_indexes("asset_assignments")}
    if "uq_asset_active_assignment" not in indexes:
        op.create_index(
            "uq_asset_active_assignment",
            "asset_assignments",
            ["organization_id", "asset_id"],
            unique=True,
            postgresql_where=sa.text("status = 'ACTIVE'"),
        )
    fks = {f["name"] for f in inspector.get_foreign_keys("asset_components")}
    for column, target in [
        ("parent_component_id", "asset_components"),
        ("created_by_id", "users"),
        ("updated_by_id", "users"),
    ]:
        name = f"fk_asset_components_{column}_{target}"
        if name not in fks:
            op.create_foreign_key(name, "asset_components", target, [column], ["id"])
    sa.Enum(*DOCUMENT_TYPES, name="asset_document_type").create(bind, checkfirst=True)
    op.execute(
        "ALTER TABLE asset_documents ALTER COLUMN document_type TYPE asset_document_type USING document_type::text::asset_document_type"
    )
    for fk in inspector.get_foreign_keys("asset_inspections"):
        if fk["constrained_columns"] == ["inspected_by_id"] and fk["referred_table"] == "employees":
            # Earlier installations used employee IDs; preserve their linked identity.
            missing = bind.execute(
                sa.text(
                    "SELECT count(*) FROM asset_inspections i JOIN employees e ON e.id=i.inspected_by_id WHERE e.user_id IS NULL"
                )
            ).scalar()
            if missing:
                raise RuntimeError(
                    "Link legacy inspection employees to user accounts before upgrading"
                )
            op.drop_constraint(fk["name"], "asset_inspections", type_="foreignkey")
            op.execute(
                "UPDATE asset_inspections i SET inspected_by_id=e.user_id FROM employees e WHERE i.inspected_by_id=e.id"
            )
            op.create_foreign_key(
                "fk_asset_inspections_inspected_by_id_users",
                "asset_inspections",
                "users",
                ["inspected_by_id"],
                ["id"],
            )
    for table in [
        "asset_location_history",
        "asset_media",
        "asset_ownership_history",
        "asset_status_history",
    ]:
        if "updated_at" not in {c["name"] for c in inspector.get_columns(table)}:
            op.add_column(
                table,
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
            )
    op.alter_column("assets", "asset_number", existing_type=sa.String(20), type_=sa.String(30))


def downgrade():
    # Retain additive columns, identity repairs and enum labels to avoid destroying history.
    # The previous application ignores these extensions.
    op.drop_index("uq_asset_active_assignment", table_name="asset_assignments")
