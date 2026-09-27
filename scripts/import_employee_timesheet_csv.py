"""Import a monthly hours-grid CSV/XLSX after exact employee matching.

Dry-run is the default. Use --apply-local only against a non-production database,
or --apply only in production. Existing employee/month records are never overwritten.
"""

import argparse
import asyncio
import calendar
import csv
import difflib
import json
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path, PurePosixPath
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.core.database import build_engine
from app.core.event_loop import loop_factory
from app.models import Employee, EmployeeTimesheet, EmployeeTimesheetDay


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def parse_timesheet_csv(path: Path) -> tuple[date, list[dict]]:
    if path.suffix.lower() == ".xlsx":
        rows = _read_xlsx_rows(path)
    else:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
    if len(rows) < 3 or len(rows[1]) < 6:
        raise ValueError("Expected two header rows, daily columns, Hrs, and Total Days")

    header = rows[1]
    first_day = header[3].strip()
    month_match = re.fullmatch(r"(\d{1,2})-([A-Za-z]{3})", first_day)
    if month_match:
        month_names = {name.lower(): index for index, name in enumerate(calendar.month_abbr) if name}
        month = month_names.get(month_match.group(2).lower())
        if not month:
            raise ValueError(f"Unknown month abbreviation in {header[3]!r}")
    else:
        try:
            month = (date(1899, 12, 30) + timedelta(days=int(float(first_day)))).month
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"Could not determine report month from column: {header[3]!r}") from exc
    year_match = re.search(r"\b(20\d{2})\b", path.stem)
    if not year_match:
        raise ValueError("The source filename must contain the report year, such as 'August 2026'")
    period_start = date(int(year_match.group(1)), month, 1)
    expected_days = calendar.monthrange(period_start.year, period_start.month)[1]
    total_hours_index = 3 + expected_days
    total_days_index = total_hours_index + 1
    if len(header) <= total_days_index:
        raise ValueError(f"Expected {expected_days} daily columns followed by Hrs and Total Days")

    parsed = []
    for line_number, cells in enumerate(rows[2:], start=3):
        if not cells or not any(cell.strip() for cell in cells):
            continue
        if len(cells) <= total_days_index:
            raise ValueError(f"Row {line_number} has {len(cells)} columns; expected at least {total_days_index + 1}")
        name = cells[0].strip()
        if not name and cells[1].strip().casefold() in {"hrs", "hours", "total"}:
            continue  # Spreadsheet footer totals, not an employee record.
        if not name:
            raise ValueError(f"Row {line_number} has hours but no employee name")
        daily = {}
        for day_number, raw in enumerate(cells[3:total_hours_index], start=1):
            value = raw.strip()
            if not value:
                continue
            try:
                hours = Decimal(value)
            except Exception as exc:
                raise ValueError(f"Invalid hours at row {line_number}, day {day_number}: {value!r}") from exc
            if hours < 0 or hours > 24 or hours.as_tuple().exponent < -2:
                raise ValueError(f"Hours must be between 0 and 24 with at most 2 decimals at row {line_number}, day {day_number}")
            daily[day_number] = hours
        stated_total = Decimal(cells[total_hours_index].strip() or "0")
        calculated_total = sum(daily.values(), Decimal("0"))
        if stated_total != calculated_total:
            raise ValueError(f"Row {line_number} ({name}) Hrs total {stated_total} does not match daily sum {calculated_total}")
        parsed.append({
            "source_name": name,
            "site_name": cells[1].strip() or None,
            "daily_hours": daily,
            "total_hours": calculated_total,
            "source_total_days": cells[total_days_index].strip() or None,
            "line_number": line_number,
        })
    return period_start, parsed


def _read_xlsx_rows(path: Path) -> list[list[str]]:
    """Read the first worksheet with stdlib XML support (no spreadsheet dependency)."""
    main_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package_rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    with zipfile.ZipFile(path) as workbook:
        shared_strings = []
        try:
            root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            for item in root.findall(f"{{{main_ns}}}si"):
                shared_strings.append("".join(text.text or "" for text in item.iter(f"{{{main_ns}}}t")))
        except KeyError:
            pass

        book = ET.fromstring(workbook.read("xl/workbook.xml"))
        sheet = book.find(f".//{{{main_ns}}}sheet")
        if sheet is None:
            raise ValueError("The workbook has no worksheets")
        relationship_id = sheet.attrib.get(f"{{{rel_ns}}}id")
        relationships = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
        target = next((rel.attrib["Target"] for rel in relationships.findall(f"{{{package_rel_ns}}}Relationship")
                       if rel.attrib.get("Id") == relationship_id), None)
        if not target:
            raise ValueError("Could not locate the workbook's first worksheet")
        sheet_path = str(PurePosixPath("xl") / target) if not target.startswith("/") else target.lstrip("/")
        sheet_root = ET.fromstring(workbook.read(str(PurePosixPath(sheet_path))))

        def column_index(reference: str) -> int:
            match = re.match(r"[A-Z]+", reference.upper())
            if not match:
                raise ValueError(f"Invalid workbook cell reference: {reference}")
            result = 0
            for char in match.group(0):
                result = result * 26 + ord(char) - 64
            return result - 1

        rows = []
        for row in sheet_root.findall(f".//{{{main_ns}}}sheetData/{{{main_ns}}}row"):
            cells: dict[int, str] = {}
            for cell in row.findall(f"{{{main_ns}}}c"):
                kind = cell.attrib.get("t")
                value = cell.find(f"{{{main_ns}}}v")
                if kind == "inlineStr":
                    content = "".join(text.text or "" for text in cell.iter(f"{{{main_ns}}}t"))
                elif value is None or value.text is None:
                    content = ""
                elif kind == "s":
                    content = shared_strings[int(value.text)]
                else:
                    content = value.text
                cells[column_index(cell.attrib.get("r", ""))] = content
            rows.append([cells.get(index, "") for index in range(max(cells, default=-1) + 1)])
        return rows


def employee_name_keys(employee: Employee) -> set[str]:
    first = employee.first_name or ""
    middle = employee.middle_name or ""
    last = employee.last_name or ""
    names = {f"{first} {middle} {last}", f"{first} {last}"}
    if employee.preferred_name:
        names.update({f"{employee.preferred_name} {middle} {last}", f"{employee.preferred_name} {last}"})
    return {normalize_name(value) for value in names if normalize_name(value)}


def match_employee(source_name: str, employees: list[Employee], mapping: dict[str, str]) -> tuple[Employee | None, list[str]]:
    mapped_id = mapping.get(source_name)
    if mapped_id:
        try:
            selected_id = UUID(mapped_id)
        except ValueError:
            return None, [f"Invalid mapping UUID {mapped_id!r}"]
        selected = [employee for employee in employees if employee.id == selected_id]
        return (selected[0], []) if len(selected) == 1 else (None, [f"Mapped employee {mapped_id} is not in the selected organization"])

    key = normalize_name(source_name)
    matches = [employee for employee in employees if key in employee_name_keys(employee)]
    if len(matches) == 1:
        return matches[0], []
    if len(matches) > 1:
        return None, [f"Ambiguous exact match: {employee.employee_number} {employee.first_name} {employee.last_name}" for employee in matches]

    keys = {key: employee for employee in employees for key in employee_name_keys(employee)}
    suggestions = difflib.get_close_matches(key, list(keys), n=3, cutoff=0.72)
    return None, [f"Possible match: {keys[s].employee_number} {keys[s].first_name} {keys[s].last_name}" for s in suggestions]


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    organization_id = UUID(args.organization_id)
    period_start, records = parse_timesheet_csv(Path(args.csv))
    engine = build_engine(settings)
    matched_count = 0
    unmatched = []
    pending = []
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            employees = list((await session.scalars(select(Employee).where(
                Employee.organization_id == organization_id,
            ))).all())
            mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8")) if args.mapping else {}
            existing = {
                row.employee_id: row
                for row in (await session.scalars(select(EmployeeTimesheet).where(
                    EmployeeTimesheet.organization_id == organization_id,
                    EmployeeTimesheet.period_start == period_start,
                ))).all()
            }
            print(f"Organization: {organization_id}")
            print(f"Period: {period_start:%Y-%m}; CSV rows: {len(records)}; employees in organization: {len(employees)}")
            matched_employee_ids: dict[UUID, str] = {}
            for record in records:
                employee, suggestions = match_employee(record["source_name"], employees, mapping)
                if not employee:
                    unmatched.append((record["source_name"], suggestions))
                    print(f"UNMATCHED: {record['source_name']}" + (f" ({'; '.join(suggestions)})" if suggestions else ""))
                    continue
                matched_count += 1
                prior_source_name = matched_employee_ids.get(employee.id)
                if prior_source_name:
                    unmatched.append((record["source_name"], [f"This resolves to the same employee as CSV row {prior_source_name!r}; verify the name mapping before import."]))
                    print(f"CONFLICT: {record['source_name']} and {prior_source_name} resolve to {employee.employee_number}")
                    continue
                matched_employee_ids[employee.id] = record["source_name"]
                existing_row = existing.get(employee.id)
                if existing_row:
                    if existing_row.source_file == Path(args.csv).name:
                        print(f"ALREADY IMPORTED: {record['source_name']} ({employee.employee_number})")
                        continue
                    unmatched.append((record["source_name"], ["A timesheet already exists for this employee and period; no overwrite performed."]))
                    print(f"CONFLICT: {record['source_name']} ({employee.employee_number}) already has a {period_start:%Y-%m} timesheet")
                    continue
                pending.append((record, employee))
                print(f"MATCHED: {record['source_name']} -> {employee.employee_number} {employee.first_name} {employee.last_name}; site={record['site_name'] or '—'}; hours={record['total_hours']}")

            print(f"\nMatched: {matched_count}; ready to insert: {len(pending)}; unresolved/conflicting: {len(unmatched)}")
            if unmatched:
                print("No rows were written. Resolve every name/conflict and rerun the dry run.")
                return 2
            if not args.apply and not args.apply_local:
                print("DRY RUN ONLY. Use --apply-local for development or --apply in production.")
                return 0
            if args.apply and settings.app_env != "production":
                raise RuntimeError("Refusing to import: APP_ENV must be production when --apply is set")
            if args.apply_local and settings.app_env == "production":
                raise RuntimeError("Refusing local import: APP_ENV is production")

            for record, employee in pending:
                row = EmployeeTimesheet(
                    organization_id=organization_id,
                    employee_id=employee.id,
                    period_start=period_start,
                    site_name=record["site_name"],
                    source_file=Path(args.csv).name,
                    created_by_id=None,
                    updated_by_id=None,
                )
                session.add(row)
                await session.flush()
                for day_number, hours in record["daily_hours"].items():
                    session.add(EmployeeTimesheetDay(
                        timesheet_id=row.id,
                        organization_id=organization_id,
                        work_date=date(period_start.year, period_start.month, day_number),
                        hours=hours,
                    ))
            await session.commit()
            print(f"Imported {len(pending)} employee timesheets for {period_start:%Y-%m}.")
            return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", help="Path to the source monthly timesheet CSV")
    parser.add_argument("--organization-id", required=True, help="Organization UUID to match employees within")
    parser.add_argument("--mapping", help="Optional JSON mapping from exact CSV employee names to employee UUIDs")
    parser.add_argument("--apply", action="store_true", help="Insert after every employee is matched; requires APP_ENV=production")
    parser.add_argument("--apply-local", action="store_true", help="Insert after every employee is matched; refuses APP_ENV=production")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args), loop_factory=loop_factory))


if __name__ == "__main__":
    main()
