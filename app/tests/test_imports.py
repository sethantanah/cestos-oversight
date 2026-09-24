"""Catch import-time failures before packaging or deploying the API."""

import importlib
import pkgutil
from typing import get_type_hints

import app
from app.main import create_app
from app.services.user import UserService
from app.tests.conftest import test_settings as make_settings


def test_backend_modules_and_application_import():
    for module in pkgutil.walk_packages(app.__path__, "app."):
        if not module.name.startswith("app.tests"):
            importlib.import_module(module.name)
    application = create_app(make_settings())
    assert application.openapi()["paths"]


def test_legacy_hse_incident_routes_remain_registered():
    application = create_app(make_settings())
    registered = {
        (route.path, method)
        for route in application.routes
        for method in getattr(route, "methods", set())
    }
    assert ("/api/v1/incidents", "POST") in registered
    assert ("/api/v1/incidents", "GET") in registered
    assert ("/api/v1/incidents/{incident_id}", "GET") in registered
    assert ("/api/v1/incidents/{incident_id}", "PATCH") in registered


def test_user_service_annotations_resolve():
    for name in (
        "list_permissions",
        "list_roles",
        "create_role",
        "update_role_permissions",
        "update",
    ):
        assert get_type_hints(getattr(UserService, name))
