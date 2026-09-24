"""Validate project-linked locations for operational records."""
from sqlalchemy import select
from app.models.location import Location


async def require_site(session, organization_id, project_id, site_location_id):
    if site_location_id is None:
        return None  # Legacy records retain their original, unspecified site.
    site = await session.scalar(select(Location).where(Location.id == site_location_id,
        Location.organization_id == organization_id, Location.project_id == project_id,
        Location.is_active.is_(True), Location.archived_at.is_(None),
        Location.location_type != "HEAD_OFFICE"))
    if site is None:
        raise ValueError("Select an active site linked to this project")
    return site


async def validate_site_intervals(session, organization_id, project_id, site_location_id, intervals, shift_id=None):
    from sqlalchemy import func
    from app.models.drilling import DrillHole, DrillingShiftInterval, DrillingShiftReport
    await require_site(session, organization_id, project_id, site_location_id)
    for entry in intervals:
        hole = await session.scalar(select(DrillHole).where(DrillHole.id == entry.drill_hole_id,
            DrillHole.organization_id == organization_id, DrillHole.project_id == project_id,
            DrillHole.archived_at.is_(None)).with_for_update())
        if hole is None or hole.site_location_id != site_location_id:
            raise ValueError("Every drill hole must belong to the selected project and site")
        query = select(func.max(DrillingShiftInterval.to_depth_m)).join(DrillingShiftReport,
            DrillingShiftReport.id == DrillingShiftInterval.shift_report_id).where(
            DrillingShiftInterval.drill_hole_id == hole.id,
            DrillingShiftReport.organization_id == organization_id,
            DrillingShiftReport.archived_at.is_(None))
        if shift_id:
            query = query.where(DrillingShiftReport.id != shift_id)
        previous = await session.scalar(query) or 0
        if not shift_id:
            previous = max(previous, hole.final_depth_m or 0)
        if hole.target_depth_m and (previous >= hole.target_depth_m or entry.to_depth_m > hole.target_depth_m):
            raise ValueError(f"Drill hole {hole.hole_number} has reached its target or the interval exceeds it")
