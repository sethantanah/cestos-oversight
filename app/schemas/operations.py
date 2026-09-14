from app.schemas.common import ORMModel


class EmployeeSummary(ORMModel):
    total: int
    active: int
    assigned: int
    unassigned: int


class ProjectSummary(ORMModel):
    total: int
    active: int
    planning: int
    paused: int


class AssetSummary(ORMModel):
    total: int
    operating: int
    available: int
    maintenance: int
    breakdown: int
    unassigned: int


class OperationsSummary(ORMModel):
    employees: EmployeeSummary
    projects: ProjectSummary
    assets: AssetSummary

    active_projects: int = 0
    active_employees: int = 0
    operating_assets: int = 0
    available_employees: int = 0
    available_assets: int = 0
    breakdowns: int = 0

    critical_defects: int = 0
    expiring_employee_documents: int = 0
    expiring_equipment_registrations: int = 0
    critical_stock_items: int = 0
    pending_inventory_requests: int = 0
