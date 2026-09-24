This should become the **Daily Maintenance / Breakdown Repair Job Card** module alongside the Preventive Maintenance Job Card. The important difference is that this form is **repair/event-driven**, rather than checklist-driven.

# Daily Maintenance / Breakdown Repair Job Card — AI Implementation Specification

Build a digital form based on the supplied:

**DAILY MAINTENANCE / BREAKDOWN REPAIR JOB CARD**

It must have:

1. **Create/Edit Form** — optimized for technicians and supervisors entering repair information.
2. **View Job Card** — read-only paper-style rendering closely matching the supplied image.
3. **Print / PDF View** — reproduce the job card as a professional maintenance record.
4. Integration with **Equipment, Employees, Inventory, Projects/Locations, Defects and Maintenance History**.

The same database record must drive the Edit and View versions.

---

# 1. Overall Structure

The document consists of these sections:

```text
DAILY MAINTENANCE / BREAKDOWN REPAIR JOB CARD

A. JOB CONTROL & MACHINE IDENTIFICATION

B. REPORTED FAILURE / REQUEST

C. CORRECTIVE ACTION / WORK COMPLETED

D. PARTS, CONSUMABLES & MATERIALS

E. LABOUR & DOWNTIME

F. TEST, RELEASE & REMARKS

G. SIGN-OFF
```

Also maintain internal system fields:

```typescript
{
    id: UUID;
    organization_id: UUID;

    job_card_number: string;

    status:
        | "DRAFT"
        | "OPEN"
        | "IN_PROGRESS"
        | "AWAITING_PARTS"
        | "AWAITING_TEST"
        | "PENDING_SIGNOFF"
        | "COMPLETED"
        | "CANCELLED";

    created_at: datetime;
    created_by: UUID;
    updated_at: datetime;
    updated_by: UUID;
    completed_at: datetime | null;
}
```

---

# A. JOB CONTROL & MACHINE IDENTIFICATION

The first section of the supplied document contains two rows of machine/job information.

### Row 1

```text
Equipment        [value]

Fleet / Unit ID  [value]

Location         [value]

Hour / KM        [value]
```

### Row 2

```text
Operator / Driver  [value]

Department         [value]

Time Reported      [value]

Time Attended      [value]
```

### Data structure

```typescript
job_control: {
    equipment_id: UUID;
    equipment_name: string;

    fleet_unit_id: string;

    location_id?: UUID;
    location: string;

    hour_km: number | null;
    meter_type: "HOURS" | "KM" | "OTHER";

    operator_driver_id?: UUID;
    operator_driver_name: string;

    department: string;

    time_reported: datetime | time;
    time_attended: datetime | time;
}
```

Where possible, **Equipment**, **Operator/Driver**, **Location** and **Department** should be populated from existing master records rather than entered manually.

When equipment is selected, automatically retrieve:

```text
Equipment Name
Fleet / Unit ID
Current Location
Current Hour Meter / Odometer
```

---

# B. REPORTED FAILURE / REQUEST

This is a large free-text section.

Heading:

**REPORTED FAILURE / REQUEST**

Provide a large textarea:

```typescript
reported_failure_request: string;
```

Example:

```text
Operator reported hydraulic oil leaking from the feed
cylinder area. Feed pressure reduced during drilling and
machine response became slow.
```

The digital form should also optionally allow:

```typescript
failure_details: {
    reported_by?: UUID;
    failure_category?: string;
    priority?: "LOW" | "NORMAL" | "HIGH" | "CRITICAL";
    machine_stopped?: boolean;
    attachments?: Attachment[];
}
```

These additional fields do not necessarily need to appear on the paper-style View.

Allow technicians/operators to attach:

```text
Photos
Videos
Documents
Inspection evidence
```

---

# C. CORRECTIVE ACTION / WORK COMPLETED

The next large section is:

**CORRECTIVE ACTION / WORK COMPLETED**

Provide a large multiline field:

```typescript
corrective_action_work_completed: string;
```

Example:

```text
Inspected hydraulic feed circuit and identified damaged
pressure hose.

Isolated machine and replaced damaged hose.

Hydraulic oil level was checked and topped up.

System was pressure tested and inspected for additional
leaks.
```

Optionally allow individual actions to be recorded internally:

```typescript
corrective_actions: [
    {
        id: UUID;
        sequence: number;
        description: string;
        performed_by?: UUID;
        performed_at?: datetime;
    }
]
```

The paper View can combine these into the large **Corrective Action / Work Completed** area.

---

# D. PARTS, CONSUMABLES & MATERIALS

Reproduce the table shown in the original form.

Columns:

| Description | Part No. | Qty | Unit | Source | Condition | Old Part Ret. | Remarks |
| ----------- | -------- | --: | ---- | ------ | --------- | ------------- | ------- |

The original label **Old Part Ret.** should represent whether the removed/replaced component was returned.

### Data model

```typescript
parts_materials: [
    {
        id: UUID;

        inventory_item_id?: UUID;

        description: string;

        part_number: string;

        quantity: number;

        unit: string;

        source: string;

        condition: string;

        old_part_returned: boolean | null;

        remarks: string;
    }
]
```

---

## Parts Entry UI

The digital form should provide:

```text
PARTS, CONSUMABLES & MATERIALS

Description        Part Number
[_____________]    [____________]

Quantity           Unit
[____]             [Each ▼]

Source             Condition
[Store ▼]          [New ▼]

Old Part Returned
[Yes / No / N/A]

Remarks
[____________________________]

[ + Add Part / Material ]
```

Multiple rows must be supported.

### Suggested `Source` values

```text
Main Store
Site Store
Service Truck
External Purchase
Transferred from Another Site
Other
```

### Suggested `Condition` values

```text
New
Serviceable
Reconditioned
Used
Other
```

---

# Inventory Integration

Where the part exists in the inventory system, selecting it should automatically populate:

```text
Description
Part Number
Unit
Available Stock
Store / Location
```

When the repair is finalized, the system should be capable of creating the corresponding inventory issue transaction.

Relationship:

```text
Repair Job Card
      │
      └── Parts Used
              │
              └── Inventory Transaction
                      │
                      └── Inventory Item
```

Do not simply store inventory consumption as text.

---

# E. LABOUR & DOWNTIME

The supplied document contains the following table:

| Technician | Start | Finish | Labour Hrs | Machine Down | P/Work Hrs | Remarks |
| ---------- | ----- | ------ | ---------: | -----------: | ---------: | ------- |

The `P/Work Hrs` label should be preserved in the paper reproduction if exact visual matching is required. Internally, use a clearer field name based on the organization's intended meaning.

### Data model

```typescript
labour_entries: [
    {
        id: UUID;

        technician_id: UUID;
        technician_name: string;

        start_time: datetime;
        finish_time: datetime;

        labour_hours: decimal;

        machine_down_hours: decimal;

        p_work_hours: decimal;

        remarks: string;
    }
]
```

Allow **multiple technicians**.

Example:

```text
Technician       Start    Finish   Labour Hrs
John Doe         09:15    12:15       3.0

Machine Down     P/Work Hrs
3.0              3.0

Remarks
Hydraulic hose replacement and testing.
```

---

# Automatic Labour Calculation

Where start and finish times are provided:

```text
Labour Hours = Finish Time - Start Time
```

The system should calculate this automatically while still allowing authorized correction where necessary.

For example:

```text
Start: 09:15
Finish: 12:45

Labour Hours: 3.50
```

If 3 technicians worked for 3.5 hours each:

```text
Total Labour Hours = 10.5 technician-hours
```

Do **not** automatically interpret this as 10.5 hours of equipment downtime. Labour hours and machine downtime are different metrics.

---

# F. TEST, RELEASE & REMARKS

The supplied document provides a large section titled:

**TEST, RELEASE & REMARKS**

The digital form should provide:

```typescript
test_release: {
    test_release_remarks: string;

    test_performed: boolean;

    test_result?: "PASSED" | "FAILED" | "PASSED_WITH_OBSERVATIONS";

    machine_status?:
        | "RELEASED"
        | "RELEASED_WITH_RESTRICTIONS"
        | "AWAITING_REPAIR"
        | "AWAITING_PARTS"
        | "OUT_OF_SERVICE";

    released_at?: datetime;
}
```

The primary field rendered on the original job card is:

```text
Test, Release & Remarks
[                                               ]
[                                               ]
[                                               ]
```

Example completed text:

```text
Machine started and hydraulic system operated through
full feed cycle.

No further leaks detected.

Operating pressure normal.

Machine released back to operations.
```

---

# G. SIGN-OFF

At the bottom of the original card reproduce:

```text
Technician Sign

Supervisor Sign

Operator Sign

Date
```

### Digital structure

```typescript
sign_off: {
    technician: {
        employee_id: UUID;
        name: string;
        signature_url: string;
        signed_at: datetime;
    } | null;

    supervisor: {
        employee_id: UUID;
        name: string;
        signature_url: string;
        signed_at: datetime;
    } | null;

    operator: {
        employee_id: UUID;
        name: string;
        signature_url: string;
        signed_at: datetime;
    } | null;

    signoff_date: date | null;
}
```

Support:

```text
Draw Signature
Upload Signature
Use Authorized Saved Signature
```

The system should record who actually performed each sign-off.

---

# 2. Recommended Form/Edit Interface

The **Edit view should prioritize usability**, especially for technicians on tablets.

Do not force the data-entry page into the narrow paper table.

Example:

```text
DAILY MAINTENANCE / BREAKDOWN REPAIR

JOB CONTROL
────────────────────────────────────────────

Equipment
[TD900 Surface Core Drill ▼]

Fleet / Unit ID
[TD900-01]

Location
[Project Site A ▼]

Hour / KM
[4,281.6] [Hours ▼]


Operator / Driver
[Select Employee ▼]

Department
[Drilling Operations ▼]

Time Reported          Time Attended
[08:42]                [09:03]


REPORTED FAILURE / REQUEST
────────────────────────────────────────────

[Operator reported hydraulic leak from feed system... ]

[ Add Photos / Evidence ]


CORRECTIVE ACTION / WORK COMPLETED
────────────────────────────────────────────

[Inspected feed circuit and identified...]



PARTS, CONSUMABLES & MATERIALS
────────────────────────────────────────────

Hydraulic Hose
P/N: HYD-10291

Qty: 1       Unit: Each
Source: Site Store
Condition: New
Old Part Returned: Yes

[Edit] [Remove]

[ + Add Part ]


LABOUR & DOWNTIME
────────────────────────────────────────────

Technician: John Doe

Start: 09:03
Finish: 12:10

Labour Hours: 3.12
Machine Down Hours: 3.12

[ + Add Technician ]


TEST, RELEASE & REMARKS
────────────────────────────────────────────

Test Result
[Passed ▼]

Machine Status
[Released ▼]

Remarks
[Machine tested under operating conditions...]

```

---

# 3. View Job Card Feature

Add:

**View Job Card**

Suggested route:

```text
/maintenance/repair-job-cards/{id}/view
```

This should render a dedicated read-only document.

The View should **closely reproduce the supplied image**, rather than looking like the normal application UI.

---

# 4. Paper-Style Layout

At the top:

```text
          DAILY MAINTENANCE / BREAKDOWN REPAIR JOB CARD
```

Then the dark navy section:

```text
JOB CONTROL & MACHINE IDENTIFICATION
```

Followed by:

```text
┌───────────┬──────────┬────────────┬──────────┬──────────┬──────────┬─────────┬───────┐
│ Equipment │          │ Fleet /    │          │ Location │          │ Hour/KM │       │
│           │          │ Unit ID    │          │          │          │         │       │
├───────────┼──────────┼────────────┼──────────┼──────────┼──────────┼─────────┼───────┤
│ Operator/ │          │ Department │          │ Time     │          │ Time    │       │
│ Driver    │          │            │          │ Reported │          │ Attended│       │
└───────────┴──────────┴────────────┴──────────┴──────────┴──────────┴─────────┴───────┘
```

Then:

```text
┌──────────────────────────────────────────────────────────┐
│                REPORTED FAILURE / REQUEST                │
├──────────────────────────────────────────────────────────┤
│                                                          │
│                                                          │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

Then:

```text
┌──────────────────────────────────────────────────────────┐
│              CORRECTIVE ACTION / WORK COMPLETED          │
├──────────────────────────────────────────────────────────┤
│                                                          │
│                                                          │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

# 5. Parts Table Rendering

Render the table close to the original:

```text
              PARTS, CONSUMABLES & MATERIALS

┌────────────┬─────────┬─────┬──────┬────────┬───────────┬──────────┬─────────┐
│Description │ Part No.│ Qty │ Unit │ Source │ Condition │Old Part  │ Remarks │
│            │         │     │      │        │           │Ret.      │         │
├────────────┼─────────┼─────┼──────┼────────┼───────────┼──────────┼─────────┤
│            │         │     │      │        │           │          │         │
├────────────┼─────────┼─────┼──────┼────────┼───────────┼──────────┼─────────┤
│            │         │     │      │        │           │          │         │
├────────────┼─────────┼─────┼──────┼────────┼───────────┼──────────┼─────────┤
│            │         │     │      │        │           │          │         │
└────────────┴─────────┴─────┴──────┴────────┴───────────┴──────────┴─────────┘
```

The View should dynamically add rows if more parts were recorded.

---

# 6. Labour & Downtime Rendering

```text
                     LABOUR & DOWNTIME

┌────────────┬────────┬────────┬───────────┬──────────────┬───────────┬─────────┐
│ Technician │ Start  │ Finish │ Labour Hrs│ Machine Down │ P/Work Hrs│ Remarks │
│            │        │        │           │ Hrs          │           │         │
├────────────┼────────┼────────┼───────────┼──────────────┼───────────┼─────────┤
│            │        │        │           │              │           │         │
├────────────┼────────┼────────┼───────────┼──────────────┼───────────┼─────────┤
│            │        │        │           │              │           │         │
└────────────┴────────┴────────┴───────────┴──────────────┴───────────┴─────────┘
```

---

# 7. Test / Release Section

Reproduce the large final section:

```text
┌────────────────────────────────────────────────────────────┐
│                 TEST, RELEASE & REMARKS                    │
├────────────────────────────────────────────────────────────┤
│                                                            │
│                                                            │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

Then the signature row:

```text
┌─────────────────┬─────────────────┬─────────────────┬─────────────┐
│ Technician Sign │ Supervisor Sign │ Operator Sign   │ Date        │
│                 │                 │                 │             │
└─────────────────┴─────────────────┴─────────────────┴─────────────┘
```

Actual digital signatures should appear inside the appropriate cells.

---

# 8. Styling

The visual language should match the existing Preventive Maintenance Job Card so both forms appear to belong to the same company maintenance system.

Use:

```css
.job-card-section-title {
    background: #17344d;
    color: white;
    text-align: center;
    font-weight: 600;
    text-transform: uppercase;
}

.job-card-table {
    width: 100%;
    border-collapse: collapse;
}

.job-card-table th,
.job-card-table td {
    border: 1px solid #555;
}
```

Use the same green accent line/details as the reference document where appropriate.

---

# 9. View Actions

Outside the document itself:

```text
[← Back] [Edit] [Print] [Download PDF]
```

Depending on status:

```text
[Submit for Sign-Off]

or

[Complete Job Card]
```

These controls must not appear when printed.

---

# 10. Print Layout

Make the View suitable for **A4 portrait**, matching the proportions of this particular reference form.

```css
@media print {
    .job-card-toolbar {
        display: none !important;
    }

    @page {
        size: A4 portrait;
        margin: 7mm;
    }

    .job-card {
        width: 100%;
        box-shadow: none;
        margin: 0;
    }
}
```

Avoid page breaks through:

```text
Parts table rows
Labour rows
Signature section
Section headings
```

If content exceeds one page, create a clean continuation rather than shrinking the text until it becomes unreadable.

---

# 11. Relationship to Preventive Maintenance

Do **not** treat this as another PM checklist.

The distinction should be:

```text
MAINTENANCE
│
├── Preventive Maintenance
│     ├── PM Schedule
│     ├── PM Template
│     └── PM Job Card
│
└── Repair / Breakdown Maintenance
      ├── Failure Report
      ├── Repair Job Card
      ├── Parts Used
      ├── Labour
      ├── Downtime
      └── Machine Release
```

This second job card is especially important for tracking **unplanned equipment downtime**.

---

# 12. Recommended Workflow

Implement:

```text
Failure / Maintenance Request
        ↓
Create Repair Job Card
        ↓
Identify Equipment
        ↓
Record Failure
        ↓
Assign Technician(s)
        ↓
Time Attended
        ↓
Diagnosis / Corrective Work
        ↓
Record Parts & Consumables
        ↓
Record Labour & Downtime
        ↓
Test Machine
        ↓
Supervisor Review
        ↓
Operator Confirmation
        ↓
Machine Released
        ↓
Job Card Completed
        ↓
Maintenance History
```

A breakdown should therefore provide timestamps that can later be used for metrics such as:

```text
Time to Attend
Repair Duration
Equipment Downtime
Technician Labour Hours
Parts Cost
Total Repair Cost
Failure Frequency
Repeat Failures
MTTR
MTBF
Equipment Availability
```

---

# 13. Important Database Design

I would structure this so **both job cards share a common maintenance-work-order foundation**, rather than building two completely isolated systems:

```text
MaintenanceWorkOrder
│
├── Equipment
├── Type
│    ├── PREVENTIVE
│    ├── BREAKDOWN
│    ├── CORRECTIVE
│    └── DAILY_MAINTENANCE
│
├── Status
├── Location
├── Reported By
├── Assigned Technicians
│
├── PM Job Card
│     └── PM Inspection Items
│
├── Repair Job Card
│     ├── Failure
│     ├── Corrective Action
│     ├── Labour
│     └── Release
│
├── Parts Used
│     ↓
│   Inventory
│
├── Attachments
├── Signatures
└── Maintenance History
```

That will make your CESTOS equipment platform much cleaner because the dashboard can show **all maintenance activity for a rig/machine in one history**, regardless of whether it came from scheduled PM or an unexpected breakdown.
