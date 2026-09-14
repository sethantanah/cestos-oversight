import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.project_report import ProjectReportCreate
from app.tests.conftest import login
from app.tests.test_asset_domain import make_client_and_project, superuser_headers


def report_body(site_id):
    return {
        "site_id": site_id,
        "title": "Morning drilling",
        "report_type": "DRILLING_UPDATE",
        "report_date": "2026-01-01",
        "metres": "100.25",
        "drill_holes": 2,
        "average_depth": "40.50",
    }


@pytest.mark.parametrize(
    "change",
    [
        {"metres": "-1"},
        {"drill_holes": 1.5},
        {"average_depth": None},
        {"report_type": "PROGRESS_UPDATE"},
        {"title": "   "},
        {"report_date": (datetime.now(UTC).date() + timedelta(days=1)).isoformat()},
        {"drill_holes": 0, "average_depth": "10"},
        {"metres": "NaN"},
    ],
)
def test_report_validation(change):
    with pytest.raises(ValidationError):
        ProjectReportCreate.model_validate(
            {**report_body("00000000-0000-0000-0000-000000000001"), **change}
        )


async def test_reports_metrics_activity_files_and_isolation(client, identities, session_factory):
    headers = await superuser_headers(client, identities["admin"], session_factory)
    _, project = await make_client_and_project(client, headers)
    root = "/api/v1/projects/" + project["id"]
    await client.patch(root, headers=headers, json={"target_metres": "200", "status": "ACTIVE"})
    response = await client.post(
        "/api/v1/locations",
        headers=headers,
        json={
            "name": "North drill site",
            "location_type": "PROJECT_SITE",
            "project_id": project["id"],
        },
    )
    assert response.status_code == 201, response.text
    site = response.json()
    body = report_body(site["id"])
    response = await client.post(
        root + "/reports",
        headers=headers,
        data={"report": json.dumps(body)},
        files={"file": ("shift.txt", b"Shift report", "text/plain")},
    )
    assert response.status_code == 201, response.text
    report = response.json()
    assert report["created_by_id"] == str(identities["admin"].id)
    assert report["author_name"] == "A Admin"
    assert report["site_name"] == "North drill site"
    assert "storage_path" not in report
    response = await client.get(root + "/reports/" + report["id"] + "/attachment", headers=headers)
    assert response.status_code == 200 and response.content == b"Shift report"
    second = {
        **body,
        "title": "Afternoon drilling",
        "metres": "50.25",
        "drill_holes": 1,
        "average_depth": "10.50",
    }
    assert (
        await client.post(root + "/reports", headers=headers, data={"report": json.dumps(second)})
    ).status_code == 201
    progress = {
        k: v for k, v in body.items() if k not in {"metres", "drill_holes", "average_depth"}
    }
    progress["report_type"] = "PROGRESS_UPDATE"
    assert (
        await client.post(root + "/reports", headers=headers, data={"report": json.dumps(progress)})
    ).status_code == 201
    metrics = (await client.get(root + "/report-metrics", headers=headers)).json()
    assert Decimal(str(metrics["metres"])) == Decimal("150.50")
    assert metrics["drill_holes"] == 3
    assert Decimal(str(metrics["average_depth"])) == Decimal("30.50")
    assert Decimal(str(metrics["target_progress"])) == Decimal("75.25")
    assert metrics["reports"] == 3 and len(metrics["by_month"]) == 1
    filtered = (
        await client.get(root + "/reports?report_type=DRILLING_UPDATE&page_size=1", headers=headers)
    ).json()
    assert filtered["total"] == 2 and len(filtered["items"]) == 1 and filtered["pages"] == 2
    events = (await client.get(root + "/activity", headers=headers)).json()["items"]
    entry = next(
        e
        for e in events
        if e["action"] == "project.report_created" and e["details"]["report_id"] == report["id"]
    )
    assert entry["author_name"] == "A Admin" and entry["details"]["file_name"] == "shift.txt"
    dashboard = (await client.get("/api/v1/projects/dashboard-summary", headers=headers)).json()
    assert dashboard["reports"] == 3 and dashboard["by_status"]["ACTIVE"] == 1
    _, other_project = await make_client_and_project(client, headers)
    wrong = "/api/v1/projects/" + other_project["id"]
    assert (
        await client.post(wrong + "/reports", headers=headers, data={"report": json.dumps(body)})
    ).status_code == 422
    assert (
        await client.get(wrong + "/reports/" + report["id"] + "/attachment", headers=headers)
    ).status_code == 404
    denied = await login(client, identities["denied"])
    assert (
        await client.post(
            root + "/reports",
            headers={"Authorization": "Bearer " + denied["access_token"]},
            data={"report": json.dumps(body)},
        )
    ).status_code == 403
    other_headers = await superuser_headers(client, identities["other"], session_factory)
    for suffix in [
        "/reports",
        "/report-metrics",
        "/activity",
        "/reports/" + report["id"] + "/attachment",
    ]:
        assert (await client.get(root + suffix, headers=other_headers)).status_code == 404
    other_dashboard = (
        await client.get("/api/v1/projects/dashboard-summary", headers=other_headers)
    ).json()
    assert other_dashboard["reports"] == 0 and other_dashboard["total"] == 0
