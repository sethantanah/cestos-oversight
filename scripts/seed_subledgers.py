"""Script to seed Revenue and Cost Subledgers for all active projects.

Usage: python scripts/seed_subledgers.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath("."))
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.database import build_engine
from app.core.event_loop import loop_factory
from app.models import Asset, Project
from app.models.drilling_commercial import (
    CostCategory,
    CostSubledgerEntry,
    ProjectContract,
    RevenueCategory,
    RevenueSubledgerEntry,
)
from scripts.seed import ORGANIZATION_ID


async def seed_subledgers():
    settings = Settings()
    engine = build_engine(settings)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        # Acquire advisory lock
        await session.execute(text("SELECT pg_advisory_xact_lock(847291048)"))

        projects = (await session.scalars(
            select(Project).where(Project.organization_id == ORGANIZATION_ID)
        )).all()

        rigs = (await session.scalars(
            select(Asset).where(Asset.organization_id == ORGANIZATION_ID)
        )).all()

        contracts = (await session.scalars(
            select(ProjectContract).where(ProjectContract.organization_id == ORGANIZATION_ID)
        )).all()

        if not projects:
            print("No projects found.")
            return

        now = datetime.now(UTC)

        sample_revenues = [
            (RevenueCategory.DRILLING_METERAGE, "HQ Diamond Core Production Revenue", Decimal("180.00"), Decimal("85.00"), Decimal("15300.00")),
            (RevenueCategory.DRILLING_METERAGE, "PQ Surface Core Drilling Meterage", Decimal("95.00"), Decimal("110.00"), Decimal("10450.00")),
            (RevenueCategory.STANDBY_TIME, "Approved Client Standby (Site Weather Hold)", Decimal("12.00"), Decimal("150.00"), Decimal("1800.00")),
            (RevenueCategory.MOBILIZATION, "Rig Mobilization & Setup Fee", Decimal("1.00"), Decimal("5000.00"), Decimal("5000.00")),
            (RevenueCategory.DAYWORK, "Geological Survey & Re-logging Daywork", Decimal("8.00"), Decimal("220.00"), Decimal("1760.00")),
        ]

        sample_costs = [
            (CostCategory.FUEL, "Site Diesel Fuel Delivery (2,500 L)", Decimal("2500.00"), "LITRES", Decimal("1.80"), Decimal("4500.00")),
            (CostCategory.LABOUR, "Field Crew & Driller Shift Wages", Decimal("1.00"), "LOT", Decimal("3200.00"), Decimal("3200.00")),
            (CostCategory.MAINTENANCE_PARTS, "Hydraulic Hoses & Core Barrel Replacement", Decimal("3.00"), "UNITS", Decimal("850.00"), Decimal("2550.00")),
            (CostCategory.CONSUMABLES, "Diamond Core Bits & Drilling Fluids", Decimal("4.00"), "UNITS", Decimal("620.00"), Decimal("2480.00")),
            (CostCategory.LOGISTICS, "Heavy Transport & Mobilization Logistics", Decimal("1.00"), "LOT", Decimal("2100.00"), Decimal("2100.00")),
        ]

        inserted_rev_count = 0
        inserted_cost_count = 0

        for p_idx, p in enumerate(projects):
            rig = rigs[p_idx % len(rigs)] if rigs else None
            contract = contracts[p_idx % len(contracts)] if contracts else None

            # Check revenue entries count
            rev_count = (await session.scalars(
                select(RevenueSubledgerEntry).where(
                    RevenueSubledgerEntry.organization_id == ORGANIZATION_ID,
                    RevenueSubledgerEntry.project_id == p.id,
                )
            )).all()

            if len(rev_count) < 3:
                for r_idx, (cat, desc, qty, rate, total) in enumerate(sample_revenues):
                    post_date = now - timedelta(days=(p_idx * 5 + r_idx * 2 + 1))
                    session.add(
                        RevenueSubledgerEntry(
                            organization_id=ORGANIZATION_ID,
                            project_id=p.id,
                            rig_id=rig.id if rig else None,
                            contract_id=contract.id if contract else None,
                            revenue_category=cat,
                            description=f"{desc} - {p.name}",
                            quantity=qty,
                            unit_rate=rate,
                            total_revenue=total,
                            total_revenue_base=total,
                            currency="USD",
                            posted_at=post_date,
                        )
                    )
                    inserted_rev_count += 1

            # Check cost entries count
            cost_count = (await session.scalars(
                select(CostSubledgerEntry).where(
                    CostSubledgerEntry.organization_id == ORGANIZATION_ID,
                    CostSubledgerEntry.project_id == p.id,
                )
            )).all()

            if len(cost_count) < 3:
                for c_idx, (cat, desc, qty, uom, ucost, total) in enumerate(sample_costs):
                    post_date = now - timedelta(days=(p_idx * 5 + c_idx * 2 + 1))
                    session.add(
                        CostSubledgerEntry(
                            organization_id=ORGANIZATION_ID,
                            project_id=p.id,
                            rig_id=rig.id if rig else None,
                            cost_category=cat,
                            description=f"{desc} - {p.name}",
                            quantity=qty,
                            unit_of_measure=uom,
                            unit_cost=ucost,
                            total_cost=total,
                            total_cost_base=total,
                            currency="USD",
                            posted_at=post_date,
                        )
                    )
                    inserted_cost_count += 1

        await session.commit()
        print(f"Subledger seed completed! Inserted {inserted_rev_count} revenue entries and {inserted_cost_count} cost entries.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_subledgers(), loop_factory=loop_factory)
