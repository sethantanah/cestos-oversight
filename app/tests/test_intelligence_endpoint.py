import pytest
from httpx import AsyncClient
from app.models import User

@pytest.mark.asyncio
async def test_get_intelligence_metrics_structure(client: AsyncClient, superuser: User):
    response = await client.get("/api/v1/intelligence/metrics")
    assert response.status_code == 200
    data = response.json()

    assert "fleet_utilization" in data
    assert "fuel_efficiency" in data
    assert "drilling_performance" in data
    assert "workforce_productivity" in data
    assert "inventory_intelligence" in data
    assert "financial_summary" in data

    # Check nested fields & chart datasets
    assert "total_assets" in data["fleet_utilization"]
    assert "by_category" in data["fleet_utilization"]
    assert "by_department" in data["workforce_productivity"]
    assert "by_project" in data["workforce_productivity"]
    assert "by_category" in data["inventory_intelligence"]
