"""Seed employee data from CSV file into dev or production database."""

import argparse
import asyncio
import csv
import os
import re
import sys
import uuid
from datetime import datetime, date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, os.path.abspath("."))

from app.core.config import Settings
from app.core.database import build_engine
from app.models import Department, Employee, Location, Organization, Position
from app.models.employee import EmploymentStatus, EmploymentType
from app.services.counters import next_business_number
from scripts.seed import ORGANIZATION_ID


def parse_date_str(d_str: str | None) -> date | None:
    if not d_str or not d_str.strip():
        return None
    d_str = d_str.strip().replace("Sept", "Sep")
    for fmt in ("%m/%d/%Y", "%m/%d %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(d_str, fmt).date()
        except ValueError:
            pass
    clean_d = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", d_str)
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(clean_d, fmt).date()
        except ValueError:
            pass
    return None


def parse_name(name_str: str) -> tuple[str, str | None, str]:
    parts = [p for p in name_str.strip().split() if p]
    if not parts:
        return "Unknown", None, "Employee"
    if len(parts) == 1:
        return parts[0], None, parts[0]
    if len(parts) == 2:
        return parts[0], None, parts[1]
    return parts[0], " ".join(parts[1:-1]), parts[-1]


async def seed_employees_from_csv(
    session: AsyncSession,
    csv_file_path: str,
) -> None:
    print(f"Reading CSV from: {csv_file_path}")
    if not os.path.exists(csv_file_path):
        raise FileNotFoundError(f"CSV file not found at: {csv_file_path}")

    # Ensure Organization
    organization = await session.get(Organization, ORGANIZATION_ID)
    if organization is None:
        raise ValueError("Organization not found in database. Run seed_realistic first.")

    # Fetch lookup dicts from DB
    db_depts = (await session.scalars(select(Department))).all()
    dept_by_name = {d.name.lower(): d for d in db_depts}

    db_positions = (await session.scalars(select(Position))).all()
    pos_by_title = {p.title.lower(): p for p in db_positions}

    db_locations = (await session.scalars(select(Location))).all()
    loc_by_name = {l.name.lower(): l for l in db_locations}

    # Helper location lookup
    def match_location(site_str: str, status_str: str) -> Location | None:
        s_lower = site_str.lower().strip()
        st_lower = status_str.lower().strip()
        if "dugbe" in s_lower or "dugbe" in st_lower or "west" in s_lower:
            return loc_by_name.get("dugbe project site")
        if "zodiac" in s_lower or "zodiac" in st_lower:
            return loc_by_name.get("bentol todi project site")
        if "marshall" in s_lower or "marshall" in st_lower:
            return loc_by_name.get("paynesville central workshop & yard")
        return loc_by_name.get("monrovia head office") or loc_by_name.get("head office")

    # Helper department lookup
    def match_department(dept_str: str, pos_obj: Position | None) -> Department | None:
        d_lower = dept_str.lower().strip()
        if d_lower in ("operation", "operations"):
            return dept_by_name.get("operations")
        if "transport" in d_lower:
            return dept_by_name.get("transportation")
        if pos_obj and pos_obj.department_id:
            for d in db_depts:
                if d.id == pos_obj.department_id:
                    return d
        return dept_by_name.get("operations")

    # Helper position lookup
    def match_position(pos_str: str) -> Position | None:
        p_clean = pos_str.strip().lower()
        if not p_clean:
            return None
        if p_clean in pos_by_title:
            return pos_by_title[p_clean]
        if "driller trainee" in p_clean:
            return pos_by_title.get("trainee-driller")
        if "mechanic" in p_clean and "trianee" in p_clean:
            return pos_by_title.get("mechanic trianee")
        if p_clean == "mechanic":
            return pos_by_title.get("heavey duty mechanic")
        # Loose match
        for title, pos_obj in pos_by_title.items():
            if p_clean in title or title in p_clean:
                return pos_obj
        return None

    with open(csv_file_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        raw_rows = [r for r in reader if r.get("Employee  Names", "").strip()]

    print(f"Found {len(raw_rows)} employee records in CSV.")

    created_count = 0
    updated_count = 0

    for idx, row in enumerate(raw_rows, start=1):
        raw_name = row["Employee  Names"].strip()
        id_num_str = row.get("ID Numbers", "").strip()
        dob = parse_date_str(row.get("DOB"))
        raw_dept = row.get("Department", "").strip()
        raw_pos = row.get("Position", "").strip()
        raw_site = row.get("Site", "").strip()
        raw_status = row.get("Status", "").strip()
        contact_phone = row.get(" Contact", "").strip() or row.get("Contact", "").strip()
        hire_dt = parse_date_str(row.get("Hire Date"))

        first_name, middle_name, last_name = parse_name(raw_name)

        # Match position and department
        pos_obj = match_position(raw_pos)
        job_title = pos_obj.title if pos_obj else (raw_pos or "Employee")
        dept_obj = match_department(raw_dept, pos_obj)
        dept_name = dept_obj.name if dept_obj else "Operations"

        # Match site/location
        loc_obj = match_location(raw_site, raw_status)

        # Work email fallback
        email_prefix = f"{first_name.lower().replace('.', '')}.{last_name.lower().replace('.', '')}"
        email_prefix = re.sub(r"[^a-z0-9.]", "", email_prefix)
        work_email = f"{email_prefix}@cestos.lr"

        # Check existing employee by email or name
        existing_emp = await session.scalar(
            select(Employee).where(
                Employee.organization_id == ORGANIZATION_ID,
                (Employee.work_email == work_email)
                | ((Employee.first_name == first_name) & (Employee.last_name == last_name)),
            )
        )

        if existing_emp:
            existing_emp.first_name = first_name
            existing_emp.middle_name = middle_name or existing_emp.middle_name
            existing_emp.last_name = last_name
            existing_emp.job_title = job_title
            existing_emp.department = dept_name
            existing_emp.department_id = dept_obj.id if dept_obj else existing_emp.department_id
            existing_emp.position_id = pos_obj.id if pos_obj else existing_emp.position_id
            existing_emp.home_location_id = loc_obj.id if loc_obj else existing_emp.home_location_id
            if dob:
                existing_emp.date_of_birth = dob
            if hire_dt:
                existing_emp.hire_date = hire_dt
            if contact_phone:
                existing_emp.primary_phone = contact_phone
            updated_count += 1
            print(f"[{idx}/{len(raw_rows)}] Updated: {raw_name} ({job_title} | {dept_name})")
        else:
            if id_num_str and id_num_str.isdigit():
                emp_num = f"EMP-{int(id_num_str):04d}"
            else:
                emp_num = await next_business_number(session, ORGANIZATION_ID, "employee")

            new_emp = Employee(
                organization_id=ORGANIZATION_ID,
                employee_number=emp_num,
                first_name=first_name,
                middle_name=middle_name,
                last_name=last_name,
                job_title=job_title,
                department=dept_name,
                department_id=dept_obj.id if dept_obj else None,
                position_id=pos_obj.id if pos_obj else None,
                home_location_id=loc_obj.id if loc_obj else None,
                work_email=work_email,
                primary_phone=contact_phone or None,
                date_of_birth=dob,
                hire_date=hire_dt or date(2025, 1, 1),
                employment_type=EmploymentType.FULL_TIME,
                employment_status=EmploymentStatus.ACTIVE,
            )
            session.add(new_emp)
            created_count += 1
            print(f"[{idx}/{len(raw_rows)}] Created: {raw_name} ({emp_num} | {job_title} | {dept_name})")

    await session.commit()
    print(f"\nSuccessfully finished importing employees! Created: {created_count}, Updated: {updated_count}")


from app.core.event_loop import loop_factory


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed employees from CSV file.")
    parser.add_argument("--prod", action="store_true", help="Use production environment (.env.prod)")
    parser.add_argument(
        "--file",
        default=r"C:\Users\User\Downloads\Employee Details(Sheet2).csv",
        help="Path to employee CSV file",
    )
    args = parser.parse_args()

    env_file = ".env.prod" if args.prod else ".env"
    print(f"Loading environment from {env_file}...")
    settings = Settings(_env_file=env_file)
    engine = build_engine(settings)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with async_session() as session:
            await seed_employees_from_csv(session, args.file)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=loop_factory)
