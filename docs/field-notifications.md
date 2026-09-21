# Field Portal notifications

The header bell opens `/field-portal/notifications`. The portal and main inbox read the same notification records. Read and resolved states are shared; badges refresh every 30 seconds and when the window regains focus. Only the recipient can read, resolve, or forward a notification.

## Event and recipient matrix

| Event | Recipient | Timing |
| --- | --- | --- |
| Project assignment, transfer, change, completion or cancellation | Assigned employee | On save |
| Maintenance work order assignment or update | Assigned technician | On save |
| Maintenance completed or cancelled | Assigned technician and relevant Supervisor-role users | On save |
| Maintenance due soon | Assigned technician | Within one day of scheduled date |
| Maintenance overdue | Assigned technician and relevant Supervisor-role users | After scheduled date, then once per overdue week |
| Leave requested | Supervisor-role users whose team includes the employee | On save |
| Leave approved or rejected | Requesting employee | On decision |
| Employment contract nearing expiry | Employee and their supervisors; existing configured HR rules continue separately | 30, 14, 7 and 1 day thresholds |
| Employment contract expired | Employee and their supervisors | Once per expiry date |

Both maintenance models are covered: asset maintenance jobs and detailed maintenance work orders. The existing `scheduled_date` serves as the due date; neither model currently has a separate target closure date. Completed, cancelled, and archived detailed work orders are excluded from reminders. Unassigned jobs use their project (or the asset's active project) to identify supervisors.

Supervisor recipients require the exact Supervisor role, an active linked employee profile, and the existing direct-report/current-project team scope. Managers and administrators do not receive team alerts merely because of their title. Recipients must have active accounts in the same organization. Employee accounts resolve through `user_id`, or work email when no account is linked.

## Delivery and reliability

Each event creates its inbox notification and email queue record in the business transaction. Stable UUID keys derived from the event and recipient prevent duplicate events, including after read/resolution and during concurrent scheduler runs. The existing SMTP worker retries failed deliveries; marking an alert read does not mark an email sent.

Email subjects describe the event and links open the appropriate inbox for field-only or full-platform accounts. Leave alert messages include dates and category, not private reasons or attachments; supervisors open the protected leave view for those details.

The scheduler must be enabled and SMTP settings configured. Reminder checks run at `scheduler_interval_seconds`. If checks resume after a pause, only the current expiry threshold is sent rather than every missed threshold. No schema migration is needed for these alerts.

## Additional events worth considering

- High-severity safety incidents: site supervisors and designated HSE officers.
- Expiring licences or mandatory training: affected employees, supervisors and compliance staff.
- Low stock for critical spare parts: storekeepers and maintenance planners.

These additional event types need agreed severity thresholds and ownership rules before enabling broad email delivery.

## Verification

Tests use an isolated SQL database and mocked SMTP. They cover recipient boundaries, exact supervisor roles, both maintenance models, project fallback, contract thresholds, event deduplication, transaction rollback, leave decisions, inbox ownership, email subjects/links, and retry behavior. They do not send live emails.
