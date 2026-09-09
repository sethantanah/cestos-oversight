"""Inventory permission defaults used by bootstrap and the upgrade rollout."""

INVENTORY_PERMISSIONS = [
    "inventory.read",
    "inventory.catalog.manage",
    "inventory.admin",
    "inventory.costs.read",
    "inventory.forecast.read",
    "inventory.reconciliation.read",
    "inventory.transactions.reverse",
    "inventory.items.create",
    "inventory.items.update",
    "inventory.items.archive",
    "inventory.reservations.read",
    "inventory.reservations.manage",
]
for domain, actions in {
    "receipts": ["read", "create", "post"],
    "issues": ["read", "create", "approve", "post"],
    "returns": ["read", "create", "post"],
    "transfers": ["read", "create", "approve", "dispatch", "receive"],
    "requests": ["read", "create", "approve"],
    "adjustments": ["read", "create", "approve", "post"],
    "stock_counts": ["read", "create", "approve", "post"],
}.items():
    INVENTORY_PERMISSIONS.extend("inventory." + domain + "." + action for action in actions)


def inventory_grants(role: str) -> set[str]:
    reads = {code for code in INVENTORY_PERMISSIONS if code.endswith(".read")}
    operational = {
        code
        for code in INVENTORY_PERMISSIONS
        if any(
            code.startswith("inventory." + name + ".")
            for name in ["receipts", "issues", "returns", "transfers", "reservations", "requests"]
        )
        and not code.endswith(".approve")
    }
    if role == "Administrator":
        return set(INVENTORY_PERMISSIONS)
    if role == "Store Manager":
        return set(INVENTORY_PERMISSIONS) - {
            "inventory.costs.read",
            "inventory.transactions.reverse",
            "inventory.admin",
        } | {"inventory.read", "inventory.catalog.manage"}
    if role == "Storekeeper":
        return operational | {"inventory.read", "inventory.forecast.read"}
    if role == "Operations Manager":
        return reads - {"inventory.costs.read"} | {
            code for code in INVENTORY_PERMISSIONS if code.endswith(".approve")
        }
    if role in {"Project Manager", "Maintenance Manager"}:
        return {
            "inventory.read",
            "inventory.requests.read",
            "inventory.requests.create",
            "inventory.forecast.read",
        }
    if role == "Finance":
        return reads
    if role in {"CEO", "Auditor"}:
        return reads
    return set()
