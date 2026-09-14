import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import install_exception_handlers
from app.schemas.employee import EmployeeCreate


@pytest.fixture
def validation_client():
    app = FastAPI()
    install_exception_handlers(app)

    @app.post("/employees")
    def create_employee(payload: EmployeeCreate):
        return payload.model_dump(mode="json")

    return TestClient(app)


@pytest.mark.parametrize("status", ["SINGLE", "MARRIED", "DIVORCED", "WIDOWED", "SEPARATED"])
def test_wizard_marital_status_values(validation_client, status):
    response = validation_client.post(
        "/employees",
        json={
            "first_name": "Test",
            "last_name": "Employee",
            "marital_status": status,
            "employment_type": "FULL_TIME",
            "employment_status": "ACTIVE",
        },
    )
    assert response.status_code == 200
    assert response.json()["marital_status"] == status


def test_validation_names_fields_without_echoing_input(validation_client):
    response = validation_client.post(
        "/employees",
        json={
            "first_name": "Test",
            "last_name": "Employee",
            "marital_status": "Single",
            "personal_email": "private-invalid-value",
        },
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert "marital status" in error["message"]
    assert "personal email" in error["message"]
    assert "private-invalid-value" not in response.text
    assert "input" not in response.text
