"""Realistic seed script for Cestos Operations.

Supports clearing the database and populating realistic data for dev or prod environments.
- In prod mode (--prod): skips employee records as requested.
- In dev mode (--dev / default): seeds authentic Liberian employee records.
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath("."))
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import build_engine
from app.core.event_loop import loop_factory
from app.core.security import hash_password
from app.db.base import Base
from app.models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetComponent,
    AssetInsurance,
    AssetMeterReading,
    AssetRegistration,
    Client,
    Department,
    Employee,
    EmployeeAssignment,
    Location,
    Organization,
    Permission,
    Position,
    Project,
    Role,
    RotationPattern,
    User,
)
from app.models.asset import AssetStatus, ComponentStatus, MeterType, OwnershipType, ReadingType
from app.models.employee import AssignmentStatus, EmploymentStatus, EmploymentType
from app.models.inventory import (
    InventoryCategory,
    InventoryItem,
    InventoryStore,
    StockPolicyFields,
    Supplier,
    UnitOfMeasure,
)
from app.models.location import LocationType
from app.models.project import ProjectStatus
from app.schemas import inventory as s
from app.services.counters import next_business_number
from app.services.inventory import DOCUMENTS, InventoryService
from scripts.seed import ORGANIZATION_ID, PERMISSIONS, ROLES
from scripts.sync_inventory_permissions import sync as sync_inv_permissions


async def clear_database(session: AsyncSession) -> None:
    """Safely clear all application domain data tables in PostgreSQL."""
    print("Clearing database tables...")
    tables = [f'"{table.name}"' for table in Base.metadata.tables.values() if table.name != "alembic_version"]
    if tables:
        quoted = ", ".join(tables)
        await session.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE;"))
    print("Database cleared successfully.")


async def seed_realistic(session: AsyncSession, settings: Settings, include_employees: bool = True) -> None:
    """Seed the database with realistic operational data."""
    print(f"Starting seed (Include Employees: {include_employees})...")
    
    # 1. Organization
    organization = await session.get(Organization, ORGANIZATION_ID)
    if organization is None:
        organization = Organization(
            id=ORGANIZATION_ID,
            name="Cestos Investments Liberia Incorporated",
            legal_name="Cestos Investments Liberia Incorporated",
            country="LR",
            default_currency="USD",
            timezone="Africa/Monrovia",
        )
        session.add(organization)
        await session.flush()

    # 2. Permissions & Roles
    permissions = {p.code: p for p in (await session.scalars(select(Permission))).all()}
    for code in PERMISSIONS:
        if code not in permissions:
            permissions[code] = Permission(code=code, description=code.replace(".", ": "))
            session.add(permissions[code])
    await session.flush()

    roles = {
        r.name: r
        for r in (
            await session.scalars(select(Role).where(Role.organization_id == ORGANIZATION_ID))
        ).all()
    }
    for name in ROLES:
        if name not in roles:
            def _is_read(code: str) -> bool:
                return code.endswith(".read") or code.endswith("read_basic") or code.endswith("read_full")

            if name == "Administrator":
                grants = list(permissions.values())
            elif name in {"CEO", "Auditor"}:
                grants = [p for p in permissions.values() if _is_read(p.code)]
            elif name == "Operations Manager":
                grants = [
                    p for code, p in permissions.items()
                    if code.startswith("employees.read") or code.startswith("projects.")
                    or code.startswith("assets.") or code.startswith("asset_documents.")
                    or code.startswith("locations.") or code.startswith("clients.")
                ]
            else:
                grants = [p for p in permissions.values() if _is_read(p.code)]

            roles[name] = Role(
                organization_id=ORGANIZATION_ID,
                name=name,
                is_system_role=False,
                permissions=grants,
            )
            session.add(roles[name])
    await session.flush()

    # 3. Initial Admin User
    admin_email = "admin@example.com"
    admin_pass = "Admin32"
    if settings.initial_admin_email:
        admin_email = str(TypeAdapter(EmailStr).validate_python(settings.initial_admin_email)).lower()
    if settings.initial_admin_password:
        admin_pass = settings.initial_admin_password.get_secret_value()

    admin_user = await session.scalar(
        select(User).where(User.organization_id == ORGANIZATION_ID, User.email == admin_email)
    )
    if admin_user is None:
        admin_user = User(
            organization_id=ORGANIZATION_ID,
            email=admin_email,
            password_hash=hash_password(admin_pass),
            first_name="System",
            last_name="Administrator",
            is_superuser=True,
            roles=[roles["Administrator"]],
        )
        session.add(admin_user)
        await session.flush()

    # Sync inventory permissions
    await sync_inv_permissions(session)

    async def number(entity: str) -> str:
        return await next_business_number(session, ORGANIZATION_ID, entity)

    # 4. Departments & Positions
    dept_names = [
        "Executive Management",
        "Drilling Operations",
        "Maintenance & Engineering",
        "Supply Chain & Inventory",
        "Health, Safety & Environment",
        "Human Resources & Admin",
        "Finance & Accounting",
        "Information Technology",
    ]
    departments: dict[str, Department] = {}
    for dname in dept_names:
        dept = Department(organization_id=ORGANIZATION_ID, name=dname)
        session.add(dept)
        await session.flush()
        departments[dname] = dept

    position_specs = [
        ("Managing Director / CEO", "Executive Management", False),
        ("Operations Manager", "Drilling Operations", False),
        ("Project Manager", "Drilling Operations", False),
        ("Senior Drilling Supervisor", "Drilling Operations", True),
        ("Diamond Core Driller", "Drilling Operations", True),
        ("Offbearer / Rig Helper", "Drilling Operations", True),
        ("Chief Maintenance Engineer", "Maintenance & Engineering", False),
        ("Heavy Rig Mechanic", "Maintenance & Engineering", True),
        ("Rig Electrician", "Maintenance & Engineering", True),
        ("Store Manager", "Supply Chain & Inventory", False),
        ("Senior Storekeeper", "Supply Chain & Inventory", False),
        ("Procurement Officer", "Supply Chain & Inventory", False),
        ("HSE Superintendent", "Health, Safety & Environment", True),
        ("HR Officer", "Human Resources & Admin", False),
        ("Senior Accountant", "Finance & Accounting", False),
        ("IT Systems Specialist", "Information Technology", False),
    ]
    positions: dict[str, Position] = {}
    for title, dept_n, is_field in position_specs:
        pos = Position(
            organization_id=ORGANIZATION_ID,
            title=title,
            department_id=departments[dept_n].id,
            is_field_role=is_field,
        )
        session.add(pos)
        await session.flush()
        positions[title] = pos

    # 5. Employees (Dev only)
    employees: dict[str, Employee] = {}
    if include_employees:
        liberian_employees = [
            ("Flomo", "Kollie", "Managing Director / CEO", "Executive Management", "+231886512345", "flomo.kollie@cestos.lr"),
            ("Gaye", "Dennis", "Operations Manager", "Drilling Operations", "+231886429876", "gaye.dennis@cestos.lr"),
            ("Tarpeh", "Sirleaf", "Project Manager", "Drilling Operations", "+231770123456", "tarpeh.sirleaf@cestos.lr"),
            ("Mulbah", "Massaquoi", "Senior Drilling Supervisor", "Drilling Operations", "+231886998877", "mulbah.massaquoi@cestos.lr"),
            ("Juah", "Sackie", "Diamond Core Driller", "Drilling Operations", "+231775554321", "juah.sackie@cestos.lr"),
            ("Kpadeh", "Weah", "Diamond Core Driller", "Drilling Operations", "+231886112233", "kpadeh.weah@cestos.lr"),
            ("Togba", "Tweh", "Chief Maintenance Engineer", "Maintenance & Engineering", "+231778889900", "togba.tweh@cestos.lr"),
            ("Zinnah", "Barclay", "Heavy Rig Mechanic", "Maintenance & Engineering", "+231886776655", "zinnah.barclay@cestos.lr"),
            ("Fahnbulleh", "Tubman", "Store Manager", "Supply Chain & Inventory", "+231773332211", "fahnbulleh.tubman@cestos.lr"),
            ("Massaquoi", "Coleman", "Senior Storekeeper", "Supply Chain & Inventory", "+231886221144", "massaquoi.coleman@cestos.lr"),
            ("Nagbe", "Juah", "HSE Superintendent", "Health, Safety & Environment", "+231774445566", "nagbe.juah@cestos.lr"),
            ("Nyahn", "Flomo", "IT Systems Specialist", "Information Technology", "+231886334455", "nyahn.flomo@cestos.lr"),
        ]
        for fname, lname, ptitle, dname, phone, email in liberian_employees:
            emp = Employee(
                organization_id=ORGANIZATION_ID,
                employee_number=await number("employee"),
                first_name=fname,
                last_name=lname,
                job_title=ptitle,
                department=dname,
                department_id=departments[dname].id,
                position_id=positions[ptitle].id if ptitle in positions else None,
                work_email=email,
                primary_phone=phone,
                employment_type=EmploymentType.FULL_TIME,
                employment_status=EmploymentStatus.ACTIVE,
                hire_date=date(2023, 3, 1),
            )
            session.add(emp)
            await session.flush()
            employees[ptitle] = emp

    # 6. Clients (Matching User Projects)
    client_specs = [
        ("Zodiac Gold", "Zodiac Gold Limited", "Mark Thompson", "m.thompson@zodiacgold.com", "+231880112233"),
        ("Mansa Resources", "Mansa Resources Ltd", "Sarah Jenkins", "s.jenkins@mansaresources.com", "+231770223344"),
        ("West26 Liberia", "West26 Mining Corp", "David O'Connor", "d.oconnor@west26.com", "+231880334455"),
        ("Hamak Gold Liberia", "Hamak Gold Plc", "Amara Konneh", "a.konneh@hamakgold.com", "+231770445566"),
        ("CMS Liberia", "Consolidated Mining Services", "Jean-Luc Dupont", "j.dupont@cmsliberia.com", "+231880556677"),
        ("Western Cluster Liberia", "Western Cluster Limited", "Rajesh Kumar", "r.kumar@westerncluster.com", "+231770667788"),
        ("Solway Mining", "Solway Mining Incorporated", "Pavel Ivanov", "p.ivanov@solwaymining.com", "+231880778899"),
    ]
    clients: dict[str, Client] = {}
    for cname, legal, ccontact, cemail, cphone in client_specs:
        client = Client(
            organization_id=ORGANIZATION_ID,
            client_number=await number("client"),
            name=cname,
            legal_name=legal,
            primary_contact_name=ccontact,
            primary_contact_email=cemail,
            primary_contact_phone=cphone,
            country="LR",
        )
        session.add(client)
        await session.flush()
        clients[cname] = client

    # 7. Projects (Exact 7 Projects from Prompt)
    project_specs = [
        ("Zodiac Gold - Todi Project", "Zodiac Gold", "Gold Exploration", Decimal("3000"), ProjectStatus.ACTIVE, date(2025, 1, 15), "An ongoing gold exploration and resource definition drilling program at the Zodiac Gold Limited project in Bentol, Montserrado County. The campaign encompasses 3,000 meters of advanced exploration drilling."),
        ("Mansa Resources - Dugbe", "Mansa Resources", "Gold Exploration", Decimal("15000"), ProjectStatus.ACTIVE, date(2024, 6, 1), "An ongoing large-scale gold exploration and resource definition drilling program at the Dugbe Gold Project. The campaign encompasses 15,000 meters of advanced drilling to support geological modeling and expansion."),
        ("West26 - Gibi Iron Ore Project", "West26 Liberia", "Iron Ore Exploration", Decimal("8000"), ProjectStatus.COMPLETED, date(2020, 3, 1), "Completed over 8,000m drilling campaign at the Gibi Project."),
        ("Hamak Gold Exploration", "Hamak Gold Liberia", "Gold Exploration", Decimal("1400"), ProjectStatus.COMPLETED, date(2023, 1, 10), "A specialized 1,400m drilling campaign targeting gold mineralization at the Nimba project. Provided rapid sample recovery and precision drilling to support exploration targets."),
        ("Konobo Gold Exploration", "CMS Liberia", "Gold Exploration", Decimal("4500"), ProjectStatus.COMPLETED, date(2021, 5, 20), "Execution of a 4,500-meter gold exploration drilling program at Konobo. The program focused on high-recovery coring techniques in complex geological formations."),
        ("Bomi Iron Ore", "Western Cluster Liberia", "Iron Ore & Geotechnical", Decimal("5000"), ProjectStatus.COMPLETED, date(2021, 2, 1), "Completed 5,000m drilling program at Bomi Hills."),
        ("Solway Mount Belleh Project", "Solway Mining", "Iron Ore Exploration", Decimal("2000"), ProjectStatus.COMPLETED, date(2021, 8, 15), "Completed 2,000m iron ore exploration drilling program, delivering high-fidelity geological data for resource estimation."),
    ]
    projects: dict[str, Project] = {}
    pm_emp = employees.get("Project Manager") if include_employees else None
    for pname, cname, ptype, depth_m, status, sdate, desc in project_specs:
        prj = Project(
            organization_id=ORGANIZATION_ID,
            project_number=await number("project"),
            client_id=clients[cname].id,
            name=pname,
            description=desc,
            project_type=ptype,
            target_metres=depth_m,
            status=status,
            start_date=sdate,
            project_manager_id=pm_emp.id if pm_emp else None,
            default_currency="USD",
        )
        session.add(prj)
        await session.flush()
        projects[pname] = prj

    # 8. Locations
    location_specs = [
        ("Monrovia Head Office", LocationType.HEAD_OFFICE, None, "Sinkor, Monrovia, Montserrado County"),
        ("Paynesville Central Workshop & Yard", LocationType.WORKSHOP, None, "Paynesville Industrial Area, Montserrado"),
        ("Bentol Todi Project Site", LocationType.PROJECT_SITE, "Zodiac Gold - Todi Project", "Bentol, Montserrado County"),
        ("Dugbe Project Site", LocationType.PROJECT_SITE, "Mansa Resources - Dugbe", "Sinoe County"),
        ("Gibi Project Site", LocationType.PROJECT_SITE, "West26 - Gibi Iron Ore Project", "Margibi County"),
        ("Nimba Exploration Site", LocationType.PROJECT_SITE, "Hamak Gold Exploration", "Nimba County"),
        ("Konobo Project Site", LocationType.PROJECT_SITE, "Konobo Gold Exploration", "Grand Gedeh County"),
        ("Bomi Hills Project Site", LocationType.PROJECT_SITE, "Bomi Iron Ore", "Bomi County"),
        ("Mount Belleh Project Site", LocationType.PROJECT_SITE, "Solway Mount Belleh Project", "Nimba County"),
    ]
    locations: dict[str, Location] = {}
    for lname, ltype, prj_name, addr in location_specs:
        loc = Location(
            organization_id=ORGANIZATION_ID,
            location_number=await number("location"),
            name=lname,
            location_type=ltype,
            project_id=projects[prj_name].id if prj_name else None,
            address=addr,
            country="LR",
        )
        session.add(loc)
        await session.flush()
        locations[lname] = loc

    # 9. Asset Categories
    cat_specs = [
        ("Diamond Core Drill Rig", "CAT-RIG-DC", MeterType.ENGINE_HOURS, True, True, True, True),
        ("Support Pickup Vehicle", "CAT-VEH-PU", MeterType.ODOMETER_KM, True, True, True, True),
        ("Heavy Transport Truck", "CAT-VEH-TRK", MeterType.ODOMETER_KM, True, True, True, True),
        ("Diesel Power Generator", "CAT-PWR-GEN", MeterType.OPERATING_HOURS, False, False, False, False),
        ("Air Compressor", "CAT-CMP-AIR", MeterType.OPERATING_HOURS, False, False, False, False),
    ]
    categories: dict[str, AssetCategory] = {}
    for cname, code, mtype, is_mob, req_reg, req_ins, req_op in cat_specs:
        cat = AssetCategory(
            organization_id=ORGANIZATION_ID,
            name=cname,
            code=code,
            default_meter_type=mtype,
            is_mobile=is_mob,
            requires_registration=req_reg,
            requires_insurance=req_ins,
            requires_operator=req_op,
        )
        session.add(cat)
        await session.flush()
        categories[cname] = cat

    # 10. Equipment / RIGS (Exact 5 RIGS from Prompt)
    rig_specs = [
        (
            "Torque Drill TD900 DTMS Surface Core Drill Rig",
            "Torque Drill",
            "TD900 DTMS",
            "TD900-2023-01",
            "Diamond Core Drill Rig",
            AssetStatus.OPERATING,
            Decimal("1850.0"),
            "Bentol Todi Project Site",
            "Diamond Core | Depth: NQ 1,200 m / HQ 725 m / PQ 480 m | Diameter: NQ / HQ / PQ | Drive: Hydraulic\nFeatures: Crawler-mounted surface core drill, Variable/reversible hydraulic rotation motor, 3 or 6 m rod pull, 45° off horizontal to 90° vertical drilling range, Available mine-spec safety systems",
        ),
        (
            "Boart Longyear LF90D Surface Coring Drill",
            "Boart Longyear",
            "LF90D",
            "BL-LF90D-4412",
            "Diamond Core Drill Rig",
            AssetStatus.OPERATING,
            Decimal("2400.0"),
            "Dugbe Project Site",
            "Diamond Core | Depth: NQ 1,064 m / HQ 722 m / PQ 476 m | Diameter: BQ / NQ / HQ / PQ | Drive: Hydraulic\nFeatures: Telescoping mast with dump capability, Crawler, truck or skid mounting capability, Hydraulic side-shifting drill head, Interlocked rotation barrier, Simple hydraulic system designed for ease of maintenance",
        ),
        (
            "Atlas Copco Christensen CS1000 P4 Core Drill",
            "Atlas Copco",
            "Christensen CS1000 P4",
            "AC-CS1000-8819",
            "Diamond Core Drill Rig",
            AssetStatus.AVAILABLE,
            Decimal("1920.0"),
            "Paynesville Central Workshop & Yard",
            "Diamond Core | Depth: BQ 1,070 m / NQ 610 m / HQ 460 m / PQ 305 m | Diameter: BQ / NQ / HQ / PQ | Drive: Hydraulic\nFeatures: Two units in fleet, Modular design for remote-area mobilisation, Hydraulic variable-speed reversible drill head, 45° to 90° drilling angle, 20 ft (6.09 m) rod pull",
        ),
        (
            "Son-Mak Levent 2002 RX-6 Core Drill Rig",
            "Son-Mak",
            "Levent 2002 RX-6",
            "SM-RX6-2022-09",
            "Diamond Core Drill Rig",
            AssetStatus.STANDBY,
            Decimal("1450.0"),
            "Paynesville Central Workshop & Yard",
            "Diamond Core | Depth: 750–2,000 m depending on configuration | Diameter: B–P Wireline / Conventional | Drive: Fully hydraulic\nFeatures: Designed for surface exploration drilling, Automatic rod removal and clamping, Integrated operator control panel, Skid, wheel or crawler mounting configurations, Hydraulic cylinder feed system",
        ),
        (
            "Ingetrol Explorer Plus MD3",
            "Ingetrol",
            "Explorer Plus MD3",
            "ING-MD3-305",
            "Diamond Core Drill Rig",
            AssetStatus.OPERATING,
            Decimal("980.0"),
            "Dugbe Project Site",
            "Diamond Core | Depth: BQ 600 m / NQ 450 m / HQ 300 m | Diameter: BQ / NQ / HQ | Drive: Hydraulic\nFeatures: Man-portable and helicopter-support configuration, Maximum component weight of 245 kg, Adjustable mast from -90° to -20°, 3 m NQ rod pull and 1.5 m HQ rod pull, Skid-mounted for remote mobilisation",
        ),
    ]

    assets: dict[str, Asset] = {}
    mech_emp = employees.get("Heavy Rig Mechanic") if include_employees else None
    driller_emp = employees.get("Diamond Core Driller") if include_employees else None

    for aname, mfr, mdl, sn, cat_n, status, reading, loc_n, notes_txt in rig_specs:
        rig_asset = Asset(
            organization_id=ORGANIZATION_ID,
            asset_number=await number("asset"),
            category_id=categories[cat_n].id,
            name=aname,
            manufacturer=mfr,
            model=mdl,
            serial_number=sn,
            year_of_manufacture=2023,
            ownership_type=OwnershipType.OWNED,
            meter_type=MeterType.ENGINE_HOURS,
            current_meter_reading=reading,
            status=status,
            default_location_id=locations[loc_n].id,
            responsible_employee_id=mech_emp.id if mech_emp else None,
            primary_operator_id=driller_emp.id if driller_emp else None,
            notes=notes_txt,
        )
        session.add(rig_asset)
        await session.flush()
        assets[aname] = rig_asset

    # Additional Support Fleet
    support_assets = [
        ("Support Pickup-001 (Toyota Hilux)", "Toyota", "Hilux 4x4 Double Cab", "SN-TH-88102", "Support Pickup Vehicle", MeterType.ODOMETER_KM, Decimal("35400.0"), "Bentol Todi Project Site"),
        ("Support Pickup-002 (Toyota Landcruiser)", "Toyota", "Land Cruiser Hardtop", "SN-TLC-99401", "Support Pickup Vehicle", MeterType.ODOMETER_KM, Decimal("42100.0"), "Dugbe Project Site"),
        ("Heavy Supply Truck (MAN TGS 6x6)", "MAN", "TGS 33.400 6x6", "SN-MAN-6601", "Heavy Transport Truck", MeterType.ODOMETER_KM, Decimal("68000.0"), "Paynesville Central Workshop & Yard"),
        ("Site Generator 250kVA (CAT C9)", "Caterpillar", "C9 250kVA", "SN-CAT-250KVA-02", "Diesel Power Generator", MeterType.OPERATING_HOURS, Decimal("2100.0"), "Bentol Todi Project Site"),
        ("High-Pressure Air Compressor (Atlas Copco XRVS)", "Atlas Copco", "XRVS 476", "SN-AC-XRVS-301", "Air Compressor", MeterType.OPERATING_HOURS, Decimal("1800.0"), "Dugbe Project Site"),
    ]
    for aname, mfr, mdl, sn, cat_n, meter_t, reading, loc_n in support_assets:
        s_asset = Asset(
            organization_id=ORGANIZATION_ID,
            asset_number=await number("asset"),
            category_id=categories[cat_n].id,
            name=aname,
            manufacturer=mfr,
            model=mdl,
            serial_number=sn,
            year_of_manufacture=2022,
            ownership_type=OwnershipType.OWNED,
            meter_type=meter_t,
            current_meter_reading=reading,
            status=AssetStatus.OPERATING,
            default_location_id=locations[loc_n].id,
        )
        session.add(s_asset)
        await session.flush()
        assets[aname] = s_asset

    # 11. Asset Assignments
    if include_employees and driller_emp:
        rig1 = assets["Torque Drill TD900 DTMS Surface Core Drill Rig"]
        todi_loc = locations["Bentol Todi Project Site"]
        todi_prj = projects["Zodiac Gold - Todi Project"]
        session.add(
            AssetAssignment(
                organization_id=ORGANIZATION_ID,
                assignment_number=await number("assignment"),
                asset_id=rig1.id,
                project_id=todi_prj.id,
                location_id=todi_loc.id,
                responsible_employee_id=driller_emp.id,
                assigned_at=datetime(2025, 1, 15, 8, 0, tzinfo=UTC),
                status=AssignmentStatus.ACTIVE,
            )
        )
        await session.flush()

    # 12. Inventory Master Data (Units, Categories, Suppliers, Stores, Items)
    inv_service = InventoryService(session, admin_user)

    units_data = [
        ("Meter", "m", "LENGTH", 2),
        ("Litre", "L", "VOLUME", 2),
        ("Piece", "pcs", "QUANTITY", 0),
        ("Box", "box", "QUANTITY", 0),
        ("Set", "set", "QUANTITY", 0),
        ("Pair", "pair", "QUANTITY", 0),
        ("Kilogram", "kg", "MASS", 2),
        ("Drum (208L)", "drum", "VOLUME", 0),
        ("Pail (20L)", "pail", "VOLUME", 0),
        ("Roll", "roll", "QUANTITY", 0),
    ]
    units: dict[str, UnitOfMeasure] = {}
    for uname, symbol, cat_str, prec in units_data:
        u = UnitOfMeasure(
            organization_id=ORGANIZATION_ID,
            name=uname,
            symbol=symbol,
            category=cat_str,
            precision=prec,
        )
        session.add(u)
        await session.flush()
        units[symbol] = u

    inv_categories_data = [
        ("Diamond Core Bits & Reamers", "CAT-BITS", True, False, False, False, False),
        ("Drill Rods & Casing", "CAT-RODS", True, False, False, False, False),
        ("Core Drilling Mud & Fluids", "CAT-FLUIDS", True, False, False, False, False),
        ("Core Trays & Sampling Supplies", "CAT-SAMPLES", True, False, False, False, False),
        ("Oils & Hydraulic Lubricants", "CAT-LUBRICANTS", True, False, True, False, False),
        ("Mechanical & Engine Spares", "CAT-SPARES", False, True, False, False, False),
        ("Hydraulic Hoses & Seals", "CAT-HYDRAULICS", False, True, True, False, False),
        ("Field Safety & PPE", "CAT-PPE", True, False, False, True, False),
        ("Specialized Drilling Tools", "CAT-TOOLS", False, False, False, False, True),
    ]
    inv_categories: dict[str, InventoryCategory] = {}
    for cname, ccode, is_con, is_sp, is_lub, is_ppe, is_tool in inv_categories_data:
        icat = InventoryCategory(
            organization_id=ORGANIZATION_ID,
            name=cname,
            code=ccode,
            is_consumable=is_con,
            is_spare_part=is_sp,
            is_lubricant=is_lub,
            is_ppe=is_ppe,
            is_tool=is_tool,
        )
        session.add(icat)
        await session.flush()
        inv_categories[cname] = icat

    # Suppliers
    suppliers_data = [
        ("Liberia Mining & Exploration Supplies Ltd", "Boakai Sirleaf", "sales@lmes-liberia.com", "+231886111222"),
        ("West Africa Drilling Consumables Corp", "Emanuel Gaye", "orders@wadc-africa.com", "+231777222333"),
        ("Boart Longyear Field Service West Africa", "Dave Higgins", "support@boartlongyear.com", "+231886333444"),
        ("Monrovia Industrial & Safety Gear", "Comfort Dennis", "info@monroviasafety.lr", "+231777444555"),
    ]
    suppliers: dict[str, Supplier] = {}
    for sname, scontact, semail, sphone in suppliers_data:
        sup = Supplier(
            organization_id=ORGANIZATION_ID,
            name=sname,
            contact_name=scontact,
            email=semail,
            phone=sphone,
        )
        session.add(sup)
        await session.flush()
        suppliers[sname] = sup

    # Stores
    store_mgr = employees.get("Store Manager") if include_employees else None
    stores_data = [
        ("Central Warehouse Store", "Monrovia Head Office", "MAIN_WAREHOUSE"),
        ("Central Mechanical Workshop Store", "Paynesville Central Workshop & Yard", "WORKSHOP_STORE"),
        ("Todi Site Project Store", "Bentol Todi Project Site", "PROJECT_STORE"),
        ("Dugbe Site Project Store", "Dugbe Project Site", "PROJECT_STORE"),
        ("Gibi Site Project Store", "Gibi Project Site", "PROJECT_STORE"),
    ]
    stores: dict[str, InventoryStore] = {}
    for sname, loc_n, stype in stores_data:
        store = InventoryStore(
            organization_id=ORGANIZATION_ID,
            store_number=await number("inventory_store"),
            name=sname,
            location_id=locations[loc_n].id,
            store_type=stype,
            manager_employee_id=store_mgr.id if store_mgr else None,
        )
        session.add(store)
        await session.flush()
        stores[sname] = store

    # Items Matched to RIGS & Drilling Operations
    items_data = [
        ("NQ Impregnated Diamond Core Bit (Matrix 9)", "SKU-BIT-NQ-M9", "Diamond Core Bits & Reamers", "pcs", "Boart Longyear Field Service West Africa", Decimal("450.00"), Decimal("10"), Decimal("25"), "HIGH", "Boart Longyear", "BL-NQ-M9"),
        ("HQ Impregnated Diamond Core Bit (Matrix 9)", "SKU-BIT-HQ-M9", "Diamond Core Bits & Reamers", "pcs", "Boart Longyear Field Service West Africa", Decimal("580.00"), Decimal("8"), Decimal("20"), "HIGH", "Boart Longyear", "BL-HQ-M9"),
        ("PQ Heavy Duty Diamond Core Bit", "SKU-BIT-PQ-HD", "Diamond Core Bits & Reamers", "pcs", "Boart Longyear Field Service West Africa", Decimal("720.00"), Decimal("5"), Decimal("10"), "HIGH", "Boart Longyear", "BL-PQ-HD"),
        ("NQ Wireline Drill Rods (3.0m)", "SKU-ROD-NQ-3M", "Drill Rods & Casing", "pcs", "West Africa Drilling Consumables Corp", Decimal("185.00"), Decimal("50"), Decimal("100"), "HIGH", "Torque Drill", "TD-ROD-NQ3M"),
        ("HQ Wireline Drill Rods (3.0m)", "SKU-ROD-HQ-3M", "Drill Rods & Casing", "pcs", "West Africa Drilling Consumables Corp", Decimal("240.00"), Decimal("40"), Decimal("80"), "HIGH", "Torque Drill", "TD-ROD-HQ3M"),
        ("PQ Wireline Drill Rods (3.0m)", "SKU-ROD-PQ-3M", "Drill Rods & Casing", "pcs", "West Africa Drilling Consumables Corp", Decimal("310.00"), Decimal("20"), Decimal("40"), "HIGH", "Torque Drill", "TD-ROD-PQ3M"),
        ("NQ Heavy Duty Diamond Reaming Shell", "SKU-RMS-NQ-HD", "Diamond Core Bits & Reamers", "pcs", "Liberia Mining & Exploration Supplies Ltd", Decimal("320.00"), Decimal("5"), Decimal("15"), "MEDIUM", "Atlas Copco", "AC-RMS-NQ"),
        ("HQ Heavy Duty Diamond Reaming Shell", "SKU-RMS-HQ-HD", "Diamond Core Bits & Reamers", "pcs", "Liberia Mining & Exploration Supplies Ltd", Decimal("410.00"), Decimal("5"), Decimal("15"), "MEDIUM", "Atlas Copco", "AC-RMS-HQ"),
        ("CR-600 High Yield Polymer Fluid Additive (25kg)", "SKU-MUD-CR600-25KG", "Core Drilling Mud & Fluids", "box", "West Africa Drilling Consumables Corp", Decimal("85.00"), Decimal("30"), Decimal("60"), "MEDIUM", "AMC Mud", "AMC-CR600"),
        ("Ultra-Gel Premium Bentonite Mud (25kg)", "SKU-MUD-BENT-25KG", "Core Drilling Mud & Fluids", "box", "West Africa Drilling Consumables Corp", Decimal("35.00"), Decimal("100"), Decimal("200"), "MEDIUM", "Baroid", "BAR-ULTRA"),
        ("HQ Plastic Core Storage Trays (Holds 3m)", "SKU-TRAY-HQ-3M", "Core Trays & Sampling Supplies", "pcs", "Liberia Mining & Exploration Supplies Ltd", Decimal("12.50"), Decimal("200"), Decimal("500"), "HIGH", "CorePro", "CP-HQ-TRAY"),
        ("NQ Plastic Core Storage Trays (Holds 4.5m)", "SKU-TRAY-NQ-4M", "Core Trays & Sampling Supplies", "pcs", "Liberia Mining & Exploration Supplies Ltd", Decimal("14.00"), Decimal("200"), Decimal("500"), "HIGH", "CorePro", "CP-NQ-TRAY"),
        ("ISO VG 68 Premium Hydraulic Fluid (208L Drum)", "SKU-OIL-HYD68-208L", "Oils & Hydraulic Lubricants", "drum", "Liberia Mining & Exploration Supplies Ltd", Decimal("650.00"), Decimal("10"), Decimal("25"), "HIGH", "TotalEnergies", "TOTAL-AZOLLA-68"),
        ("15W-40 Heavy Duty Diesel Engine Oil (208L Drum)", "SKU-OIL-15W40-208L", "Oils & Hydraulic Lubricants", "drum", "Liberia Mining & Exploration Supplies Ltd", Decimal("580.00"), Decimal("8"), Decimal("20"), "HIGH", "TotalEnergies", "TOTAL-RUBIA-15W40"),
        ("EP-2 High Performance Rig Grease (18kg Pail)", "SKU-LUB-GREASE-18KG", "Oils & Hydraulic Lubricants", "pail", "Liberia Mining & Exploration Supplies Ltd", Decimal("95.00"), Decimal("15"), Decimal("30"), "MEDIUM", "Mobil", "MOBILGREASE-XHP222"),
        ("Boart Longyear LF90D Rotation Head Seal Kit", "SKU-SPR-BL-LF90D-SEALS", "Hydraulic Hoses & Seals", "set", "Boart Longyear Field Service West Africa", Decimal("290.00"), Decimal("3"), Decimal("6"), "HIGH", "Boart Longyear", "BL-SK-90D"),
        ("Torque Drill TD900 Main Hydraulic Pump Assembly", "SKU-SPR-TD900-PUMP", "Mechanical & Engine Spares", "pcs", "West Africa Drilling Consumables Corp", Decimal("3400.00"), Decimal("1"), Decimal("2"), "HIGH", "Rexroth", "REX-A10VO45"),
        ("Atlas Copco CS1000 Feed Cylinder O-Ring Kit", "SKU-SPR-AC-CS1000-ORING", "Hydraulic Hoses & Seals", "set", "Liberia Mining & Exploration Supplies Ltd", Decimal("145.00"), Decimal("4"), Decimal("8"), "MEDIUM", "Atlas Copco", "AC-ORING-CS1K"),
        ("Ingetrol MD3 Portable Mud Pump Assembly", "SKU-SPR-ING-MD3-PUMP", "Mechanical & Engine Spares", "pcs", "West Africa Drilling Consumables Corp", Decimal("1850.00"), Decimal("1"), Decimal("2"), "HIGH", "Ingetrol", "ING-PUMP-MD3"),
        ("Rig Heavy Duty Leather Safety Gloves", "SKU-PPE-GLOVES-LTHR", "Field Safety & PPE", "pair", "Monrovia Industrial & Safety Gear", Decimal("8.50"), Decimal("50"), Decimal("150"), "MEDIUM", "SafetyFirst", "SF-GLV-HD"),
        ("Mining Steel-Toe Safety Boots", "SKU-PPE-BOOTS-STEEL", "Field Safety & PPE", "pair", "Monrovia Industrial & Safety Gear", Decimal("65.00"), Decimal("20"), Decimal("50"), "HIGH", "Caterpillar Boots", "CAT-BOOT-ST"),
        ("High-Visibility Reflective Field Safety Vest", "SKU-PPE-VEST-HIVIS", "Field Safety & PPE", "pcs", "Monrovia Industrial & Safety Gear", Decimal("12.00"), Decimal("40"), Decimal("100"), "MEDIUM", "SafetyFirst", "SF-VEST-HIVIS"),
        ("Heavy Duty Hydraulic Torque Wrench Set", "SKU-TOL-TRQ-WRENCH", "Specialized Drilling Tools", "set", "Monrovia Industrial & Safety Gear", Decimal("850.00"), Decimal("2"), Decimal("4"), "HIGH", "Enerpac", "ENR-WRENCH-SET"),
        ("Hydraulic Core Splitter Cutter Blade", "SKU-TOL-CORE-BLADE", "Specialized Drilling Tools", "pcs", "Liberia Mining & Exploration Supplies Ltd", Decimal("175.00"), Decimal("4"), Decimal("10"), "MEDIUM", "CorePro", "CP-BLADE-HYD"),
    ]

    items: dict[str, InventoryItem] = {}
    main_store = stores["Central Warehouse Store"]

    for iname, sku_val, cat_n, u_sym, sup_n, cost_val, min_qty, reorder_qty, crit_val, mfr_val, part_num in items_data:
        item = InventoryItem(
            organization_id=ORGANIZATION_ID,
            item_number=await number("inventory_item"),
            sku=sku_val,
            name=iname,
            category_id=inv_categories[cat_n].id,
            base_unit_id=units[u_sym].id,
            preferred_supplier_id=suppliers[sup_n].id,
            standard_unit_cost=cost_val,
            minimum_stock_level=min_qty,
            reorder_quantity=reorder_qty,
            criticality=crit_val,
            manufacturer=mfr_val,
            manufacturer_part_number=part_num,
            is_consumable=inv_categories[cat_n].is_consumable,
            is_returnable=inv_categories[cat_n].is_tool,
        )
        session.add(item)
        await session.flush()
        items[iname] = item

    # 13. Create Opening Stock Balances via Receipts
    await session.commit()

    opening_items = []
    for item in items.values():
        opening_items.append({
            "item_id": item.id,
            "unit_id": item.base_unit_id,
            "quantity": 100 if item.criticality == "HIGH" else 50,
            "unit_cost": str(item.standard_unit_cost or Decimal("10.00")),
        })

    sup_obj = list(suppliers.values())[0]
    await inv_service.document_save(
        "receipts",
        s.InventoryDocumentCreate.model_validate({
            "reference_number": "REC-OPENING-2025",
            "store_id": main_store.id,
            "supplier_id": sup_obj.id,
            "purpose": "OPENING_BALANCE",
            "items": opening_items,
        }),
    )

    doc_row = (
        await session.scalars(
            select(DOCUMENTS["receipts"][0]).where(
                DOCUMENTS["receipts"][0].organization_id == ORGANIZATION_ID,
                DOCUMENTS["receipts"][0].reference_number == "REC-OPENING-2025",
            )
        )
    ).first()

    if doc_row:
        await inv_service.action("receipts", doc_row.id, "post", s.InventoryAction())

    await session.commit()
    print("Realistic seed completed successfully!")


async def run_seed_cli() -> None:
    """CLI launcher for seed_realistic script."""
    parser = argparse.ArgumentParser(description="Seed Cestos database with realistic operational data.")
    parser.add_argument("--env-file", type=str, default=".env", help="Path to environment file (default: .env)")
    parser.add_argument("--prod", action="store_true", help="Run in production mode (loads .env.prod and excludes employee data)")
    parser.add_argument("--dev", action="store_true", help="Run in development mode (loads .env and includes employee data)")
    parser.add_argument("--no-employees", action="store_true", help="Exclude employee data")
    parser.add_argument("--no-clear", action="store_true", help="Do not clear existing database tables before seeding")

    args = parser.parse_args()

    env_file = args.env_file
    include_employees = not args.no_employees

    if args.prod:
        env_file = ".env.prod"
        include_employees = False
    elif args.dev:
        env_file = ".env"
        include_employees = True

    print(f"Loading environment from {env_file}...")
    settings = Settings(_env_file=env_file)
    engine = build_engine(settings)

    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            if not args.no_clear:
                async with session.begin():
                    await clear_database(session)

            await seed_realistic(session, settings, include_employees=include_employees)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_seed_cli(), loop_factory=loop_factory)
