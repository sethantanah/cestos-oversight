# Procurement

Future tables: suppliers, purchase_requests, purchase_request_items, purchase_orders,
purchase_order_items, goods_receipts. Supplier → purchase order → goods receipt → inventory transaction.
Receipts may partially fulfill order lines; capture quantities, units and inspection state. Posting a
receipt and its inventory movement should be atomic and idempotent. Preserve approval and pricing history.
