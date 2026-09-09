# Inventory

Future tables: inventory_categories, inventory_items, inventory_locations, inventory_transactions.
Derive stock from receipts, issues, transfers, returns, adjustments, consumption and disposal. Use
immutable posted transactions and compensating corrections. Transfers balance origin and destination
atomically. Link movements to projects, maintenance orders and goods receipts. Define units and decimal
precision before valuation or reorder calculations. Do not store quantity as the only source of truth.
