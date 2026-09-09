# Module boundaries and historical data

One organization owns all operational records. Cross-domain foreign keys remain in the same PostgreSQL
database; modules are code boundaries rather than isolated databases. New organization-owned tables
should use UUIDMixin, TimestampMixin, OrganizationMixin and, where appropriate, ArchiveMixin/ActorMixin.
Repositories start with organization_query(); writes verify that all related IDs belong to that tenant.
Use composite tenant foreign keys for cross-domain links where practical, with indexes supporting
organization/date and related-record queries. Services own atomic transactions across module boundaries.

Master entities describe employees, assets, suppliers and projects. Events and history tables record
assignments, movement, consumption, meter readings, breakdowns and work. Never replace assignment
history with a current_project_id column or stock transactions with a mutable quantity field. Close an
assignment interval and create the next interval. Correct posted movements with reversing events and
replacement entries; retain actor, timestamp and reason. Use decimal values and explicit units/currencies.

The future chain is people/assets/fuel/consumables/maintenance → project operations → drilling output
→ costs/revenue → project margin. Analytics should consume authoritative transactions; derived summaries
may be rebuilt. Define event dates, shift boundaries, units, currency handling and meter reset history
before implementing cost/metre, fuel/hour, availability, utilization, MTBF or MTTR.
