"""Optional development demo data; never runs in production seeding.

Usage: uv run python -m scripts.seed_demo
Idempotent: skips records that already exist (matched by name/number scope).
Requires the base seed (organization, roles, permissions) to exist.
"""

import asyncio
from datetime import UTC, date, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.core.database import build_engine
from app.core.event_loop import loop_factory
from app.models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetComponent,
    AssetDefect,
    AssetInspection,
    AssetInsurance,
    AssetLocationHistory,
    AssetMedia,
    AssetMeterReading,
    AssetRegistration,
    AssetStatusHistory,
    Client,
    Department,
    Employee,
    EmployeeAssignment,
    EmployeeAssetAuthorization,
    EmployeeDocument,
    EmployeeEmergencyContact,
    EmployeeFamilyMember,
    EmployeeLicense,
    EmployeeResume,
    EmployeeRotation,
    EmployeeTrainingRecord,
    Location,
    Position,
    Project,
    RotationPattern,
    Skill,
)
from app.models.asset import AssetStatus, ComponentStatus, MeterType, OwnershipType, ReadingType
from app.models.employee import (
    AssignmentStatus,
    AuthorizationStatus,
    AuthorizationType,
    DocumentType,
    EmploymentStatus,
    EmploymentType,
    LicenseStatus,
    LicenseType,
    RelationshipType,
    RotationStatus,
    TrainingStatus,
    VerificationStatus,
)
from app.models.location import LocationType
from app.models.project import ProjectStatus
from app.services.counters import next_business_number
from scripts.seed import ORGANIZATION_ID


async def main() -> None:
    settings = get_settings()
    engine = build_engine(settings)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            async with session.begin():
                await session.execute(text("SELECT pg_advisory_xact_lock(736284902)"))

                async def number(entity: str) -> str:
                    return await next_business_number(session, ORGANIZATION_ID, entity)

                # ---- clients ----
                clients: dict[str, Client] = {}
                for name in ["Demo Mining Client A", "Demo Exploration Client B"]:
                    existing = (
                        await session.scalars(
                            select(Client).where(
                                Client.organization_id == ORGANIZATION_ID,
                                Client.name == name,
                            )
                        )
                    ).first()
                    if existing is None:
                        existing = Client(
                            organization_id=ORGANIZATION_ID,
                            client_number=await number("client"),
                            name=name,
                            country="LR",
                        )
                        session.add(existing)
                        await session.flush()
                    clients[name] = existing

                # ---- departments & positions ----
                departments: dict[str, Department] = {}
                for dname in ["Executive", "Operations", "Drilling", "Maintenance", "HSE"]:
                    existing_dept = (
                        await session.scalars(
                            select(Department).where(
                                Department.organization_id == ORGANIZATION_ID,
                                Department.name == dname,
                            )
                        )
                    ).first()
                    if existing_dept is None:
                        existing_dept = Department(
                            organization_id=ORGANIZATION_ID, name=dname
                        )
                        session.add(existing_dept)
                        await session.flush()
                    departments[dname] = existing_dept
                positions: dict[str, Position] = {}
                for title, dept_name in [
                    ("Operations Manager", "Operations"),
                    ("Project Manager", "Operations"),
                    ("Senior Driller", "Drilling"),
                    ("Driller", "Drilling"),
                    ("Rig Mechanic", "Maintenance"),
                    ("Driver", "Operations"),
                    ("HSE Officer", "HSE"),
                    ("Storekeeper", "Operations"),
                ]:
                    existing_pos = (
                        await session.scalars(
                            select(Position).where(
                                Position.organization_id == ORGANIZATION_ID,
                                Position.title == title,
                            )
                        )
                    ).first()
                    if existing_pos is None:
                        existing_pos = Position(
                            organization_id=ORGANIZATION_ID,
                            title=title,
                            department_id=departments[dept_name].id,
                            is_field_role=title in {"Senior Driller", "Driller", "Rig Mechanic", "Driver"},
                        )
                        session.add(existing_pos)
                        await session.flush()
                    positions[title] = existing_pos

                # ---- rotation patterns ----
                patterns: dict[str, RotationPattern] = {}
                for pname, on, off in [("28/14", 28, 14), ("21/7", 21, 7)]:
                    existing_pat = (
                        await session.scalars(
                            select(RotationPattern).where(
                                RotationPattern.organization_id == ORGANIZATION_ID,
                                RotationPattern.name == pname,
                            )
                        )
                    ).first()
                    if existing_pat is None:
                        existing_pat = RotationPattern(
                            organization_id=ORGANIZATION_ID, name=pname, days_on=on, days_off=off
                        )
                        session.add(existing_pat)
                        await session.flush()
                    patterns[pname] = existing_pat

                # ---- employees ----
                employees: dict[str, Employee] = {}
                employee_positions = {
                    "CEO": None,
                    "Operations Manager": "Operations Manager",
                    "Project Manager": "Project Manager",
                    "Driller": "Driller",
                    "Mechanic": "Rig Mechanic",
                    "Driver": "Driver",
                    "Storekeeper": "Storekeeper",
                }
                employee_departments = {
                    "CEO": "Executive",
                    "Operations Manager": "Operations",
                    "Project Manager": "Operations",
                    "Driller": "Drilling",
                    "Mechanic": "Maintenance",
                    "Driver": "Operations",
                    "Storekeeper": "Operations",
                }
                for job in [
                    "CEO",
                    "Operations Manager",
                    "Project Manager",
                    "Driller",
                    "Mechanic",
                    "Driver",
                    "Storekeeper",
                ]:
                    existing_emp = (
                        await session.scalars(
                            select(Employee).where(
                                Employee.organization_id == ORGANIZATION_ID,
                                Employee.job_title == job,
                                Employee.first_name == "Demo",
                            )
                        )
                    ).first()
                    if existing_emp is None:
                        dept_name = employee_departments[job]
                        pos_title = employee_positions[job]
                        existing_emp = Employee(
                            organization_id=ORGANIZATION_ID,
                            employee_number=await number("employee"),
                            first_name="Demo",
                            last_name=job.replace(" ", ""),
                            job_title=job,
                            department=dept_name,
                            department_id=departments[dept_name].id,
                            position_id=positions[pos_title].id if pos_title else None,
                            work_email=f"demo.{job.replace(' ', '').lower()}@example.com",
                            primary_phone="+231770000000",
                            employment_type=EmploymentType.FULL_TIME,
                            employment_status=EmploymentStatus.ACTIVE,
                            hire_date=date(2024, 1, 15),
                            contract_start_date=date(2024, 1, 15),
                            contract_end_date=date(2027, 1, 14),
                        )
                        session.add(existing_emp)
                        await session.flush()
                    employees[job] = existing_emp

                # ---- projects ----
                projects: dict[str, Project] = {}
                for pname, client_name, status in [
                    ("Project Alpha", "Demo Mining Client A", ProjectStatus.ACTIVE),
                    ("Project Bravo", "Demo Exploration Client B", ProjectStatus.PLANNING),
                ]:
                    existing_prj = (
                        await session.scalars(
                            select(Project).where(
                                Project.organization_id == ORGANIZATION_ID,
                                Project.name == pname,
                            )
                        )
                    ).first()
                    if existing_prj is None:
                        existing_prj = Project(
                            organization_id=ORGANIZATION_ID,
                            project_number=await number("project"),
                            client_id=clients[client_name].id,
                            name=pname,
                            status=status,
                            project_manager_id=employees["Project Manager"].id,
                            start_date=date(2025, 1, 1),
                            default_currency="USD",
                        )
                        session.add(existing_prj)
                        await session.flush()
                    projects[pname] = existing_prj

                # ---- locations ----
                for lname, ltype, loc_project in [
                    ("Cestos Head Office", LocationType.HEAD_OFFICE, None),
                    ("Main Workshop", LocationType.WORKSHOP, None),
                    ("Main Yard", LocationType.YARD, None),
                    ("Project Alpha Site", LocationType.PROJECT_SITE, "Project Alpha"),
                    ("Project Bravo Site", LocationType.PROJECT_SITE, "Project Bravo"),
                ]:
                    existing_loc = (
                        await session.scalars(
                            select(Location).where(
                                Location.organization_id == ORGANIZATION_ID,
                                Location.name == lname,
                            )
                        )
                    ).first()
                    if existing_loc is None:
                        session.add(
                            Location(
                                organization_id=ORGANIZATION_ID,
                                location_number=await number("location"),
                                name=lname,
                                location_type=ltype,
                                project_id=projects[loc_project].id if loc_project else None,
                                country="LR",
                            )
                        )
                        await session.flush()

                # ---- asset categories ----
                categories: dict[str, AssetCategory] = {}
                cat_specs = [
                    ("Diamond Drill Rig", "CAT-DD", MeterType.ENGINE_HOURS, True, False, False, True),
                    ("RC Drill Rig", "CAT-RC", MeterType.ENGINE_HOURS, True, False, False, True),
                    ("Pickup", "CAT-PU", MeterType.ODOMETER_KM, True, True, True, False),
                    ("Truck", "CAT-TRK", MeterType.ODOMETER_KM, True, True, True, False),
                    ("Generator", "CAT-GEN", MeterType.OPERATING_HOURS, False, False, False, False),
                    ("Compressor", "CAT-CMP", MeterType.OPERATING_HOURS, False, False, False, False),
                ]
                for cname, code, meter_t, is_mob, req_reg, req_ins, req_op in cat_specs:
                    existing_cat = (
                        await session.scalars(
                            select(AssetCategory).where(
                                AssetCategory.organization_id == ORGANIZATION_ID,
                                AssetCategory.name == cname,
                            )
                        )
                    ).first()
                    if existing_cat is None:
                        existing_cat = AssetCategory(
                            organization_id=ORGANIZATION_ID,
                            name=cname,
                            code=code,
                            default_meter_type=meter_t,
                            is_mobile=is_mob,
                            requires_registration=req_reg,
                            requires_insurance=req_ins,
                            requires_operator=req_op,
                        )
                        session.add(existing_cat)
                        await session.flush()
                    categories[cname] = existing_cat

                # ---- locations map ----
                locations: dict[str, Location] = {}
                loc_list = (
                    await session.scalars(
                        select(Location).where(Location.organization_id == ORGANIZATION_ID)
                    )
                ).all()
                for l in loc_list:
                    locations[l.name] = l

                # ---- assets ----
                assets: dict[str, Asset] = {}
                asset_specs = [
                    ("CDR-001", "Diamond Drill Rig", AssetStatus.OPERATING, MeterType.ENGINE_HOURS, "Sandvik", "DE810", "SN-DE810-9012", 2450.5, "Project Alpha Site"),
                    ("CDR-002", "Diamond Drill Rig", AssetStatus.AVAILABLE, MeterType.ENGINE_HOURS, "Boart Longyear", "LF90D", "SN-LF90D-3341", 1200.0, "Main Yard"),
                    ("RC-001", "RC Drill Rig", AssetStatus.OPERATING, MeterType.ENGINE_HOURS, "Schramm", "T450WS", "SN-SCH-8831", 3100.0, "Project Bravo Site"),
                    ("Pickup-001", "Pickup", AssetStatus.AVAILABLE, MeterType.ODOMETER_KM, "Toyota", "Hilux 4x4", "SN-TH-99120", 45200.0, "Main Yard"),
                    ("Pickup-002", "Pickup", AssetStatus.OPERATING, MeterType.ODOMETER_KM, "Toyota", "Land Cruiser HZJ79", "SN-LC-77123", 28100.0, "Project Alpha Site"),
                    ("Truck-001", "Truck", AssetStatus.OPERATING, MeterType.ODOMETER_KM, "MAN", "TGS 33.400 6x6", "SN-MAN-11029", 68000.0, "Project Alpha Site"),
                    ("Truck-002", "Truck", AssetStatus.UNDER_MAINTENANCE, MeterType.ODOMETER_KM, "Mercedes-Benz", "Actros 3344", "SN-MB-44812", 112000.0, "Main Workshop"),
                    ("Generator-001", "Generator", AssetStatus.STANDBY, MeterType.OPERATING_HOURS, "Caterpillar", "C15 500kVA", "SN-CAT-500KVA-01", 1850.0, "Main Yard"),
                    ("Generator-002", "Generator", AssetStatus.OPERATING, MeterType.OPERATING_HOURS, "Cummins", "QSB7-G5 200kVA", "SN-CUM-200KVA-08", 3420.0, "Project Bravo Site"),
                    ("Compressor-001", "Compressor", AssetStatus.OPERATING, MeterType.OPERATING_HOURS, "Atlas Copco", "XRVS 476", "SN-AC-XRVS-991", 2150.0, "Project Alpha Site"),
                ]
                admin_user = (
                    await session.scalars(select(Employee).where(Employee.organization_id == ORGANIZATION_ID))
                ).first()
                mech = employees.get("Mechanic")
                for aname, cat_name, status, meter, mfr, mdl, sn, reading, loc_n in asset_specs:
                    existing_asset = (
                        await session.scalars(
                            select(Asset).where(
                                Asset.organization_id == ORGANIZATION_ID,
                                Asset.name == aname,
                            )
                        )
                    ).first()
                    if existing_asset is None:
                        loc_obj = locations.get(loc_n)
                        existing_asset = Asset(
                            organization_id=ORGANIZATION_ID,
                            asset_number=await number("asset"),
                            category_id=categories[cat_name].id,
                            name=aname,
                            manufacturer=mfr,
                            model=mdl,
                            serial_number=sn,
                            year_of_manufacture=2022,
                            ownership_type=OwnershipType.OWNED,
                            meter_type=meter,
                            current_meter_reading=reading,
                            status=status,
                            default_location_id=loc_obj.id if loc_obj else None,
                            responsible_employee_id=mech.id if mech else None,
                        )
                        session.add(existing_asset)
                        await session.flush()
                    assets[aname] = existing_asset

                # ---- asset components ----
                for c_name, asset_key, c_type, mfr in [
                    ("Caterpillar C9.3 Diesel Engine", "CDR-001", "Engine", "Caterpillar"),
                    ("Rexroth Hydraulic Pump Main", "CDR-001", "Hydraulics", "Bosch Rexroth"),
                    ("Sandvik Rotation Head RH-10", "CDR-001", "Drill Head", "Sandvik"),
                    ("Cummins QSB6.7 Engine", "RC-001", "Engine", "Cummins"),
                ]:
                    rig_obj = assets.get(asset_key)
                    if rig_obj:
                        has_comp = (
                            await session.scalars(
                                select(AssetComponent).where(
                                    AssetComponent.organization_id == ORGANIZATION_ID,
                                    AssetComponent.asset_id == rig_obj.id,
                                    AssetComponent.name == c_name,
                                )
                            )
                        ).first()
                        if not has_comp:
                            session.add(
                                AssetComponent(
                                    organization_id=ORGANIZATION_ID,
                                    asset_id=rig_obj.id,
                                    name=c_name,
                                    component_type=c_type,
                                    manufacturer=mfr,
                                    status=ComponentStatus.INSTALLED,
                                )
                            )

                # ---- insurance records ----
                for asset_key, provider, policy in [
                    ("Pickup-001", "Liberia Insurance Corp", "LIC-POL-2025-001"),
                    ("Pickup-002", "Liberia Insurance Corp", "LIC-POL-2025-002"),
                    ("Truck-001", "African International Insurance", "AII-TRK-8812"),
                ]:
                    pu = assets.get(asset_key)
                    if pu:
                        has_ins = (
                            await session.scalars(
                                select(AssetInsurance).where(
                                    AssetInsurance.organization_id == ORGANIZATION_ID,
                                    AssetInsurance.asset_id == pu.id,
                                )
                            )
                        ).first()
                        if not has_ins:
                            session.add(
                                AssetInsurance(
                                    organization_id=ORGANIZATION_ID,
                                    asset_id=pu.id,
                                    provider=provider,
                                    policy_number=policy,
                                    coverage_type="Comprehensive Commercial Vehicle",
                                    start_date=date(2025, 1, 1),
                                    expiry_date=date(2026, 1, 1),
                                    status="ACTIVE",
                                )
                            )

                # ---- registrations ----
                for asset_key, reg_num, authority in [
                    ("Pickup-001", "LR-PU-4501", "Ministry of Transport Liberia"),
                    ("Pickup-002", "LR-PU-4502", "Ministry of Transport Liberia"),
                    ("Truck-001", "LR-TRK-9901", "Ministry of Transport Liberia"),
                ]:
                    truck_obj = assets.get(asset_key)
                    if truck_obj:
                        has_reg = (
                            await session.scalars(
                                select(AssetRegistration).where(
                                    AssetRegistration.organization_id == ORGANIZATION_ID,
                                    AssetRegistration.asset_id == truck_obj.id,
                                )
                            )
                        ).first()
                        if not has_reg:
                            session.add(
                                AssetRegistration(
                                    organization_id=ORGANIZATION_ID,
                                    asset_id=truck_obj.id,
                                    registration_type="Vehicle License",
                                    registration_number=reg_num,
                                    issuing_authority=authority,
                                    issue_date=date(2025, 1, 1),
                                    expiry_date=date(2026, 1, 1),
                                    status="ACTIVE",
                                )
                            )

                # ---- sample assignments ----
                alpha_site = locations.get("Project Alpha Site")
                driller = employees.get("Driller")
                if driller and projects.get("Project Alpha"):
                    has_active = (
                        await session.scalars(
                            select(EmployeeAssignment).where(
                                EmployeeAssignment.organization_id == ORGANIZATION_ID,
                                EmployeeAssignment.employee_id == driller.id,
                                EmployeeAssignment.status == AssignmentStatus.ACTIVE,
                            )
                        )
                    ).first()
                    if has_active is None:
                        session.add(
                            EmployeeAssignment(
                                organization_id=ORGANIZATION_ID,
                                assignment_number=await number("assignment"),
                                employee_id=driller.id,
                                project_id=projects["Project Alpha"].id,
                                location_id=alpha_site.id if alpha_site else None,
                                role_on_project="Driller",
                                start_date=date(2025, 6, 1),
                                status=AssignmentStatus.ACTIVE,
                            )
                        )
                rig = assets.get("CDR-001")
                if rig and driller and projects.get("Project Alpha"):
                    has_rig = (
                        await session.scalars(
                            select(AssetAssignment).where(
                                AssetAssignment.organization_id == ORGANIZATION_ID,
                                AssetAssignment.asset_id == rig.id,
                                AssetAssignment.status == AssignmentStatus.ACTIVE,
                            )
                        )
                    ).first()
                    if has_rig is None:
                        session.add(
                            AssetAssignment(
                                organization_id=ORGANIZATION_ID,
                                assignment_number=await number("assignment"),
                                asset_id=rig.id,
                                project_id=projects["Project Alpha"].id,
                                location_id=alpha_site.id if alpha_site else None,
                                responsible_employee_id=driller.id,
                                assigned_at=datetime(2025, 6, 1, 8, 0, tzinfo=UTC),
                                status=AssignmentStatus.ACTIVE,
                            )
                        )
        print("Demo seed complete.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=loop_factory)
