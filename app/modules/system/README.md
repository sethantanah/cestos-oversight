# System

Future tables: approvals, alerts, notifications, attachments, comments. Audit logs are already
implemented centrally. Shared records retain organization, entity reference, actor and creation time.
Entity references must be validated through tenant-aware services. Attachments require storage keys,
content metadata and authorization; never trust a caller-supplied file path. Approval state transitions
retain history. Use an outbox for reliable future external notifications committed with domain changes.
