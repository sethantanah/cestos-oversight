# Drilling operations

Future tables: drill_holes, drilling_shifts, daily_operations_reports.
Project → drill hole → drilling shift. Shifts reference assigned rigs and crews and capture output,
time, stoppages and units. Daily reports aggregate authoritative shift events with approval history.
Relate consumables/fuel usage and downtime to the relevant project, asset and shift without duplicating
inventory or maintenance source events. Calculations are deferred until measurement rules are agreed.
