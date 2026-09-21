# Notification scheduler investigation (20 September 2026)

The reported document is Full-Time Employment Agreement for EMP-000012, expiring
30 September 2026. It was inside the 14-day lead window (10 days remaining).
The expiry register incorrectly treated the nested API response as a flat row and
substituted Document / Soon / 14 days. It now displays the actual document fields.

The saved schedule had never run. The background worker did not process
notification_schedules. The evaluator also matched any rule containing EXPIRY
as an inventory rule before reaching workforce documents. Recipient selections
were employee IDs, while the evaluator only looked for user-account IDs.

The worker now processes due schedules in isolated transactions with row locks,
honours the configured frequency, and resolves both account and legacy employee
recipient IDs within the organization. Explicit recipients and role recipients
are combined. An invalid recipient selection does not fall back to unrelated users.
Schedule management now checks the relevant domain permission, including employees.alerts.manage for workforce alerts. New active schedules without eligible accounts are rejected. Empty selections
notify the schedule creator. Role membership and account activity are rechecked
on each run.

Every matching record is evaluated; the old ten-record cap is removed. Inbox and
email entries are queued atomically with deterministic keys per schedule interval,
record and recipient. Manual reruns in the same interval do not duplicate delivery.
Daily schedules remind again in the next interval. ONCE does not automatically
repeat. MONTHLY advances by a calendar month. EMAIL-only deliveries do not appear
in the inbox. SMTP failures retain the retry queue and record the exception class.
A failed alert generator no longer prevents email delivery or other schedules.

Rules use actual document expiry dates, rotation work end dates, inventory lot
expiry with stock remaining, stock reorder points, open maintenance due dates,
equipment status, and project expected end dates. The unimplemented project budget
threshold option was removed rather than generating arbitrary active-project alerts.
Expired active documents remain eligible until renewed, rejected, or archived.

Read-only preview command: scripts/preview_notification_schedules.py. This never
queues or sends messages. The latest preview found three active EXPIRY ALERT
schedules with 1, 2, and 3 eligible recipients respectively; each matched the same
contract. Overlapping schedules deliver independently. No saved schedule was deleted
or disabled during the investigation. No manual live email was sent.

# Field Portal access and work completion

Only the exact Supervisor role exposes Planning, Manage Shifts, Stores & Consumables,
work creation, Schedule Service, and Report HSE controls. Basic staff retain fuel
refill and tank-dip endpoints through an active linked employee profile.

My Work and equipment maintenance use /field-portal/work-orders, which returns only
records assigned to the logged-in employee across both maintenance registers.
Supervisor Planning can list team assignments for review. Notes and individual
checklist updates persist; employees cannot remove checklist requirements by replacing
the list. Completion requires all tasks checked and remains awaiting approval.
Only a Supervisor responsible for that team can approve. Approval is stored separately
from completion and is displayed as APPROVED in Field Portal. Closed/approved work
cannot be edited through the employee endpoint.

Migration 20260920_field_work_progress adds checklist, field_notes, approved_at, and
approved_by_id to both maintenance tables. It was applied successfully. Existing
records are preserved. Existing checklists that only lived in browser state cannot
be recovered from the database; newly dispatched checklists are now persisted.

The backend process must load the updated code for scheduled runs and the new APIs.
The database preview validates matching/recipients without claiming SMTP delivery.
