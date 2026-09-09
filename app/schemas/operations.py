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
