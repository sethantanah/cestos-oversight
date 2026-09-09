# Equipment phase delivery

Implemented against the existing asset domain described in INSTRUCTIONS.txt. Existing IDs, business counters, Workforce functionality and applied migrations were retained.

## Architecture and relationships

EquipmentService extends the existing AssetService. Organization-scoped references, row locks for assignment/transfer/meter mutations, an active-assignment unique index, and audit events protect operational history. The UI uses the existing schema-driven forms and authenticated upload/download helpers.

The existing equipment tables are extended rather than recreated: assets, asset_categories, asset_components, asset_assignments, asset_meter_readings and asset_documents. The normalized record tables are asset_location_history, asset_status_history, asset_insurance_records, asset_registrations, asset_ownership_history, asset_media, asset_inspections and asset_defects. These were already introduced by the earlier asset migration and are reconciled here.

Categories and components support parent hierarchies with cycle checks. Assignments reference projects, locations and responsible/operator employees. Compliance records can reference documents from the same asset. Defects can reference inspections/components. Inspector identity uses the existing users relationship. Media has one primary photo per asset.

## Migration

9979ee24a6d7_equipment_foundation.py follows 0006_time_leave. It reconciles component foreign keys, missing enum labels, the active assignment index, history timestamps, asset-number length and a separate asset document enum. Legacy employee-linked inspectors are mapped to linked users; migration fails clearly if such an employee has no linked account.

Applied to the working database. Upgrade/downgrade/upgrade was verified on cestos_test. Downgrade deliberately retains additive columns, enum labels and identity repairs to preserve history; it removes the new active-assignment index.

## API and UI

The API includes fleet list/filter/search, available assets, tag lookup, dashboard summary, project equipment summary, 360 overview, restore, status change, atomic transfer, meter reset, activity and status history. It also includes category editing, assignment completion/cancellation, component removal/replacement, location events, insurance, registration, ownership, inspections, defects and resolution, document verification/archive, and authenticated media upload/download/primary-photo/archive. Existing compatible URLs remain available. The running /docs and /openapi.json expose exact request contracts.

The Equipment UI now has fleet totals, category/status/compliance filters, tag lookup and a detailed equipment dialog with operational records and actions. Forms load related records through API lookups. Tabs and actions follow permissions. Photo previews use authenticated blobs. Existing session-restoration, password-reset and employee activity flows are retained.

## Permissions and audit

The catalogue includes assets.financial.read, assets.status.override, assets.meter.read/record/override, assets.documents.read/manage/verify, assets.location.read/manage, assets.ownership.read/manage, and the existing component, inspection, defect, insurance, registration, media and audit permissions. Legacy document and meter permission aliases remain supported. Financial fields are redacted without financial read permission.

scripts/sync_equipment_permissions.py registered 27 missing equipment permission codes in the working database. Existing role grants and passwords are preserved. Administrators must grant the new permissions to the appropriate existing roles; superusers can use them immediately. Fresh bootstrap roles use the expanded permission catalogue.

Audit records cover creation/update/archive/restore, status/location changes, assignment/completion/transfer, meter readings/adjustments/resets, component removal/replacement, record changes, defect resolution and media changes.

## Demo and validation

Reused the existing demo fleet, categories, projects, locations, components, insurance and registrations in scripts/seed_demo.py. Seeded cestos_test and ran the demo seed twice successfully to verify idempotence. No demo records were added to the working database.

- Backend: 80 tests passed, including existing Workforce and operational regressions.
- New equipment tests cover atomic transfer rollback, duplicate active assignments, history, hierarchy cycles, component replacement, critical-defect eligibility, financial redaction, meter override permissions and reset history, photo upload/download/primary selection, and same-asset document validation.
- Frontend: 7 tests passed, including two new equipment permission/lookup tests.
- JavaScript syntax checks passed. API startup and the sign-in page were verified in the browser using the Windows-compatible event loop.
- Focused Ruff checks and mypy checks pass for the new equipment implementation. Repository-wide checks still report legacy lint/type issues, including old migrations and older employee/asset code; a clean repository-wide result is not claimed.

## Decisions and limitations

Meter staleness is centralized at seven days. Supplier remains a nullable future-integration identifier. Custody is represented by assignment responsibility/operator fields. Financial accounting, full maintenance, fuel, inventory, procurement and telematics were not started.

Derived fleet filters currently calculate over matching assets before pagination; SQL aggregation/batched loading is needed for large fleets. Related-record lists are currently unpaginated. UI controls have automated coverage; a complete signed-in visual walkthrough has not been performed. Production deployment was not performed.

The recommended next phase is Maintenance, linking plans/work orders to existing asset, meter, component, inspection and defect IDs. Before that phase, finish large-fleet query optimization and deployment-specific role assignment and visual acceptance testing.
