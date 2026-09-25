from fastapi import APIRouter

from app.api.v1.endpoints import (
    assets,
    action_tracker,
    auth,
    clients,
    commercial,
    control_tower,
    documents,
    drilling,
    email,
    employees,
    equipment,
    equipment_register,
    field_portal,
    hr,
    hse,
    intelligence,
    inventory,
    locations,
    maintenance,
    maintenance_assessments,
    notifications,
    operational_logs,
    operational_expenses,
    pm_job_cards,
    pm_tracker,
    operations,
    procurement,
    project_reports,
    projects,
    users,
    work_completion,
)

router = APIRouter()
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(employees.router)
router.include_router(pm_job_cards.router)
router.include_router(employees.assignments_router)
router.include_router(employees.departments_router)
router.include_router(employees.positions_router)
router.include_router(employees.family_router)
router.include_router(employees.emergency_router)
router.include_router(employees.resumes_router)
router.include_router(employees.documents_router)
router.include_router(employees.qualifications_router)
router.include_router(employees.skills_router)
router.include_router(employees.employee_skills_router)
router.include_router(employees.training_router)
router.include_router(employees.training_global_router)
router.include_router(employees.licenses_router)
router.include_router(employees.licenses_global_router)
router.include_router(employees.patterns_router)
router.include_router(employees.rotations_router)
router.include_router(employees.authorizations_router)
router.include_router(clients.router)
router.include_router(project_reports.router)
router.include_router(projects.router)
router.include_router(locations.router)
router.include_router(equipment.router)

covered_equipment_routes = {
    (getattr(r, "path", ""), method)
    for r in equipment.router.routes
    for method in getattr(r, "methods", [])
}
assets.router.routes[:] = [
    r
    for r in assets.router.routes
    if not any(
        (getattr(r, "path", ""), method) in covered_equipment_routes
        for method in getattr(r, "methods", [])
    )
]
router.include_router(assets.router)
router.include_router(assets.categories_router)
router.include_router(assets.asset_assignments_router)
router.include_router(operations.router)
router.include_router(hr.router)
router.include_router(field_portal.router)
# Preserve the legacy receipt URL used by already-open Field Admin Portal tabs.
router.add_api_route(
    "/fuel/deliveries/{delivery_id}/receipt",
    field_portal.download_fuel_delivery_receipt,
    methods=["GET"],
    include_in_schema=False,
)
router.include_router(work_completion.router)
router.include_router(inventory.router)
router.include_router(inventory.operational_router)
router.include_router(operational_logs.router)
router.include_router(operational_expenses.router)
router.include_router(notifications.router)
router.include_router(documents.router)
router.include_router(intelligence.router)
router.include_router(email.router)
router.include_router(drilling.router)
router.include_router(commercial.router)
# Compatibility route for portal bundles that still request the old path.
router.add_api_route(
    "/cost-subledger",
    commercial.list_cost_entries,
    methods=["GET"],
    include_in_schema=False,
)
router.include_router(maintenance.router)
router.include_router(maintenance_assessments.router)
router.include_router(action_tracker.router)
router.include_router(pm_tracker.router)
router.include_router(equipment_register.router)
router.include_router(hse.router)
# Keep the original HSE incident collection paths working for older portal
# bundles during rollout; new clients should use the explicit /hse routes.
router.add_api_route("/incidents", hse.legacy_create_incident, methods=["POST"], include_in_schema=False, status_code=201)
router.add_api_route("/incidents", hse.legacy_list_incidents, methods=["GET"], include_in_schema=False)
router.add_api_route("/incidents/{incident_id}", hse.legacy_get_incident, methods=["GET"], include_in_schema=False)
router.add_api_route("/incidents/{incident_id}", hse.legacy_update_incident, methods=["PATCH"], include_in_schema=False)
router.include_router(procurement.router)
router.include_router(control_tower.router)
