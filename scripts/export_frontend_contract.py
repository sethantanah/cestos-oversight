"""Export the API contract (routes, permissions, schemas) consumed by the frontend."""

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi.dependencies.models import Dependant

from app.main import create_app


def permission_codes(dependant: Dependant) -> Iterator[str]:
    call = dependant.call
    if call is not None and getattr(call, "__name__", "") == "dependency":
        for cell in call.__closure__ or ():
            if isinstance(cell.cell_contents, str):
                yield cell.cell_contents
    for sub in dependant.dependencies:
        yield from permission_codes(sub)


def route_contexts(router: Any) -> Iterator[Any]:
    for route in getattr(router, "routes", []):
        if hasattr(route, "effective_route_contexts"):
            yield from route.effective_route_contexts()
        elif hasattr(route, "dependant"):
            yield route


def build_contract() -> dict[str, Any]:
    app = create_app()
    document = app.openapi()
    permissions: dict[tuple[str, str], list[str]] = {}
    for route in route_contexts(app.router):
        codes = sorted(
            {code for sub in route.dependant.dependencies for code in permission_codes(sub)}
        )
        for method in route.methods:
            permissions[(route.path, method)] = codes

    routes: dict[str, dict[str, Any]] = {}
    for path, operations in document["paths"].items():
        if not path.startswith("/api/"):
            continue
        for method, operation in operations.items():
            verb = method.upper()
            body = operation.get("requestBody", {}).get("content", {}).get("application/json", {})
            routes.setdefault(path, {})[verb] = {
                "schema": body.get("schema", {}),
                "permissions": permissions.get((path, verb), []),
                "parameters": [
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter["in"] == "query"
                ],
            }
    return {"schemas": document["components"]["schemas"], "routes": routes}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: python -m scripts.export_frontend_contract <path/to/contract.json>"
        )
    contract = build_contract()
    destination = Path(sys.argv[1])
    destination.write_text(json.dumps(contract))
    print(f"Contract written to {destination}: {len(contract['routes'])} routes.")


if __name__ == "__main__":
    main()
