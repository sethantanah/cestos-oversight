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


def test_user_service_annotations_resolve():
    for name in (
        "list_permissions",
        "list_roles",
        "create_role",
        "update_role_permissions",
        "update",
    ):
        assert get_type_hints(getattr(UserService, name))
