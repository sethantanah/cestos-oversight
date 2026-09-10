from fastapi import APIRouter

from app.api.v1.endpoints import (
    assets,
    auth,
    clients,
    employees,
    equipment,
    hr,
    locations,
    operations,
    projects,
    users,
)

router = APIRouter()
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(employees.router)
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

from app.api.v1.endpoints import inventory
router.include_router(inventory.router)
router.include_router(inventory.operational_router)

from app.api.v1.endpoints import operational_logs
router.include_router(operational_logs.router)
