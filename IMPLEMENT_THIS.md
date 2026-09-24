Below is a **developer/AI implementation specification** that can be given directly to a coding agent. The goal is to reproduce the uploaded **Preventive Maintenance Job Card** as a structured digital form while preserving a **View Job Card** mode that visually renders the completed record almost exactly like the original paper form.

# Preventive Maintenance Job Card — Implementation Specification

Build a **Preventive Maintenance Job Card module** for equipment maintenance. It must have two primary interfaces:

1. **Form/Edit View** — optimized for entering maintenance information.
2. **Job Card View** — read-only, print-friendly rendering matching the supplied paper job card.

The same database record must drive both views. Do **not** store the rendered job card separately.

---

## 1. Overall Job Card Structure

The document title is:

**PREVENTIVE MAINTENANCE JOB CARD**

Organize the form into these sections:

```text
A. PM CONTROL

B. PREVENTIVE MAINTENANCE INSPECTION

C. SERVICE & DEFECT CONTROL

D. MACHINE RELEASE & SIGN-OFF
```

Each job card should also have system metadata that does not necessarily appear on the printed card:

```text
id
organization_id
job_card_number
status
created_at
created_by
updated_at
updated_by
submitted_at
completed_at
```

Suggested statuses:

```text
DRAFT
IN_PROGRESS
PENDING_SIGNOFF
COMPLETED
CANCELLED
```

---

# A. PM CONTROL

Reproduce the header information as a **4-column-pair grid**.

### Row 1

```text
PM Job Card No.     [value]
Date                [value]
PM Interval         [value]
```

### Row 2

```text
Equipment           [value]
Fleet / Unit ID     [value]
Location            [value]
```

### Row 3

```text
Technician / Team   [value]
Start Time          [value]
End Time            [value]
```

### Fields

```typescript
pm_control: {
    job_card_no: string;
    date: date;

    pm_interval: string;

    equipment: string;
    fleet_unit_id: string;
    location: string;

    technician_team: string;
    start_time: time;
    end_time: time;
}
```

### Recommended enhancements

Where the platform already contains master data, don't rely entirely on free text.

`equipment` should preferably select an equipment record and automatically populate:

```text
Equipment Name
Fleet / Unit ID
Equipment Type
Current Location
```

`technician_team` can support multiple employees:

```typescript
technicians: [
   {
      employee_id: UUID,
      name: string
   }
]
```

---

# B. PREVENTIVE MAINTENANCE INSPECTION

This is the main part of the form.

Render it as a table with these columns:

| Column                 | Purpose                                |
| ---------------------- | -------------------------------------- |
| SYSTEM / COMPONENT     | Equipment system being inspected       |
| INSPECT / SERVICE TASK | Required PM checks                     |
| CONDITION              | Condition discovered during inspection |
| ACTION TAKEN           | Maintenance/action performed           |
| PART USED / Qty        | Parts or consumables used              |
| REMARKS                | Technician comments                    |

The **System / Component** and default **Inspect / Service Task** values should come from a PM checklist/template.

Technicians mainly complete:

```text
Condition
Action Taken
Parts Used / Qty
Remarks
```

---

## 2. Inspection Rows

### ENGINE

Default inspection/service tasks:

```text
Oil level, leaks, filters
V-belt, mounts
```

Data:

```typescript
{
    system: "ENGINE",
    tasks: [
        "Oil level, leaks, filters",
        "V-belt, mounts"
    ]
}
```

---

### COOLING SYSTEM

```text
Coolant, radiator cap
Hoses / fan blades
```

---

### FUEL SYSTEM

```text
Filters / water
Separator / fuel cap
```

---

### HYDRAULIC SYSTEM

```text
Oil level, hoses,
fittings, leaks
```

---

### ELECTRICAL SYSTEM

```text
Batteries / terminals,
charging,
starter motor, lights
```

---

### DRILLING SYSTEM

```text
Feed, rotation winch,
cylinders, controls
```

---

### ROTATION HEAD

```text
Lub oil level, chuck
bolts, oil filter
```

---

### CHASSIS / STRUCTURE

```text
Bolts, cracks, pins,
bushes, mounting
points
```

---

### SAFETY SYSTEM

```text
E-stops, alarms,
guards, fire
equipment
```

---

### LUBRICATION

```text
Grease rotation head,
wire / winch sheaves
```

---

### UNDERCARRIAGE

```text
Oil / idler
Sprocket / wheel, Track
chain, Roller
```

---

### FUNCTION TEST

```text
Run machine and
verify operation
```

---

# 3. Inspection Data Model

Do not hard-code these rows directly into the completed job card.

Use a structure similar to:

```typescript
inspection_items: [
    {
        id: UUID,

        sequence: 1,

        system_component: "ENGINE",

        service_tasks: [
            "Oil level, leaks, filters",
            "V-belt, mounts"
        ],

        condition: null,

        action_taken: "",

        parts_used: [
            {
                inventory_item_id: UUID | null,
                part_name: string,
                part_number: string | null,
                quantity: number,
                unit: string | null
            }
        ],

        remarks: ""
    }
]
```

This allows different equipment types to eventually have different PM checklists.

---

# 4. Condition Field

Instead of requiring technicians to type the equipment condition every time, provide a dropdown.

Suggested options:

```text
Good
Satisfactory
Monitor
Needs Attention
Defective
Not Applicable
```

Store both the standardized condition and optional details:

```typescript
condition: "GOOD" |
           "SATISFACTORY" |
           "MONITOR" |
           "NEEDS_ATTENTION" |
           "DEFECTIVE" |
           "NOT_APPLICABLE";

condition_notes?: string;
```

The paper-style View should display a friendly label such as:

```text
Good
Needs Attention
Defective
```

---

# 5. Parts Used / Qty

The original document provides only one small column:

**PART USED / Qty**

The digital version should make this more powerful.

When the technician clicks **Add Part**, allow:

```text
Part / Consumable
Part Number
Quantity
Unit
```

Where possible, select the part from the Inventory Management module.

Example:

```text
Engine Oil Filter
P/N: OF-4021
Qty: 1
```

The paper View can compress that to:

```text
OF-4021 × 1
```

Multiple parts should be allowed for one inspection item.

This also creates the foundation for automatically deducting maintenance consumables from inventory after approval.

---

# C. SERVICE & DEFECT CONTROL

Reproduce the row shown toward the bottom of the document.

Fields:

```text
PM Result
Next PM Due
Total Labour Hr
```

Data model:

```typescript
service_defect_control: {
    pm_result: string;
    next_pm_due: date | null;
    total_labour_hours: decimal | null;
}
```

For `pm_result`, use configurable options such as:

```text
Passed
Passed with Observations
Further Maintenance Required
Machine Not Released
```

---

# D. MACHINE RELEASE & SIGN-OFF

Immediately below Section C reproduce:

```text
Machine Status
```

Suggested digital options:

```text
Released for Service
Released with Restrictions
Awaiting Repair
Out of Service
```

Data:

```typescript
machine_release: {
    machine_status: string;

    supervisor_comments_recommendations: string;

    technician_signature: Signature;
    supervisor_signature: Signature;
    operator_signature: Signature;

    technician_signed_at: datetime;
    supervisor_signed_at: datetime;
    operator_signed_at: datetime;
}
```

---

# 6. Supervisor Comments / Recommendations

Create a large textarea corresponding to:

**SUPERVISOR COMMENTS / RECOMMENDATIONS:**

Example:

```text
Hydraulic hose at rotation head showing early signs
of wear. Monitor and replace during next planned
maintenance.
```

The View mode should preserve line wrapping naturally.

---

# 7. Signature Section

The bottom row should reproduce the three signature positions from the original:

```text
Technician Signature

Supervisor Signature

Operator Signature
```

The digital form should support:

```text
Draw signature
Upload signature
Saved authorized signature
```

Each signature should also capture:

```typescript
{
    signed_by_employee_id: UUID,
    signer_name: string,
    signature_url: string,
    signed_at: datetime
}
```

Do not consider the maintenance card fully completed until required signatures have been provided.

---

# 8. Form/Edit UI

The **data-entry interface should NOT be forced to look exactly like the paper form**. Optimize this interface for technicians using laptops/tablets.

Example:

```text
PREVENTIVE MAINTENANCE

PM CONTROL
────────────────────────────────────────

Job Card No        PM Interval
[PM-000124]        [250 Hours ▼]

Equipment          Fleet / Unit ID
[TD900 ▼]          [DR-004]

Location           Date
[Project Site ▼]   [22/09/2026]

Technicians
[Select technicians...]

Start Time         End Time
[08:30]            [____]


INSPECTION
────────────────────────────────────────

ENGINE

Oil level, leaks, filters
Condition
[Good ▼]

Action Taken
[____________________________]

Parts Used
[ + Add Part ]

Remarks
[____________________________]


COOLING SYSTEM
...

```

On desktop, the inspection section can use the original table format.

On tablets/mobile devices, transform each system into a card/accordion.

---

# 9. View Job Card Feature

Add a button:

**View Job Card**

When clicked, render a dedicated route such as:

```text
/maintenance/job-cards/{id}/view
```

This view should recreate the supplied document.

The screen should look like an actual completed PM document rather than a web application form.

### Header

Dark navy title bar:

```text
PREVENTIVE MAINTENANCE JOB CARD
```

Use approximately:

```css
background: #17344d;
color: #ffffff;
```

Include the thin green accent/border visible in the reference.

---

# 10. Paper-Style Rendering

Target an **A4 landscape layout**.

```css
.job-card {
    width: 297mm;
    min-height: 210mm;
    background: white;
    margin: auto;
}
```

The visual hierarchy should resemble:

```text
┌──────────────────────────────────────────────────────────┐
│              PREVENTIVE MAINTENANCE JOB CARD            │
└──────────────────────────────────────────────────────────┘

A. PM CONTROL
┌────────────┬───────────┬──────────┬────────────┐
│ Job Card No│           │ Date     │            │
├────────────┼───────────┼──────────┼────────────┤
│ Equipment  │           │ Fleet ID │            │
├────────────┼───────────┼──────────┼────────────┤
│ Technician │           │ Start    │            │
└────────────┴───────────┴──────────┴────────────┘


B. PREVENTIVE MAINTENANCE INSPECTION

┌────────────┬──────────────┬─────────┬──────────┬─────────┬─────────┐
│ SYSTEM /   │ INSPECT /    │CONDITION│ ACTION   │ PART    │ REMARKS │
│ COMPONENT  │ SERVICE TASK │         │ TAKEN    │USED/QTY │         │
├────────────┼──────────────┼─────────┼──────────┼─────────┼─────────┤
│ ENGINE     │ ...          │         │          │         │         │
├────────────┼──────────────┼─────────┼──────────┼─────────┼─────────┤
│ COOLING    │ ...          │         │          │         │         │
│ SYSTEM     │              │         │          │         │         │
├────────────┼──────────────┼─────────┼──────────┼─────────┼─────────┤
│ ...        │              │         │          │         │         │
└────────────┴──────────────┴─────────┴──────────┴─────────┴─────────┘
```

---

# 11. Exact Inspection Ordering

Preserve this sequence in the View:

```typescript
[
    "ENGINE",
    "COOLING SYSTEM",
    "FUEL SYSTEM",
    "HYDRAULIC SYSTEM",
    "ELECTRICAL SYSTEM",
    "DRILLING SYSTEM",
    "ROTATION HEAD",
    "CHASSIS / STRUCTURE",
    "SAFETY SYSTEM",
    "LUBRICATION",
    "UNDERCARRIAGE",
    "FUNCTION TEST"
]
```

This ordering should be controlled by a `sequence` field so future templates can change it.

---

# 12. Bottom of Rendered Job Card

Render:

```text
C. SERVICE & DEFECT CONTROL
──────────────────────────────────────────────────────────

PM Result: __________      Next PM Due: __________
Total Labour Hr: ______


D. MACHINE RELEASE & SIGN-OFF
──────────────────────────────────────────────────────────

Machine Status: _________________________________________


SUPERVISOR COMMENTS / RECOMMENDATIONS:

__________________________________________________________
__________________________________________________________


Technician Signature     Supervisor Signature     Operator Signature

____________________     ____________________     ____________________
```

Where digital signatures exist, render the actual signature image above the signature line.

---

# 13. Actions in View Mode

Above the document—but **outside the printable area**—provide:

```text
[← Back]   [Edit]   [Print]   [Download PDF]
```

Optionally:

```text
[Complete Job Card]
```

The toolbar must disappear during printing.

```css
@media print {
    .job-card-toolbar {
        display: none;
    }

    @page {
        size: A4 landscape;
        margin: 7mm;
    }
}
```

The result should print as a professional maintenance document without browser navigation elements.

---

# 14. Important Architecture: PM Templates

Build this as a **template-driven system**, not a single hard-coded form.

Use:

```text
PMTemplate
    ↓
PMTemplateInspectionItems
    ↓
PMJobCard
    ↓
PMJobCardInspectionItems
```

For example:

```text
Torque Drill TD900
    └── 250 Hour PM
          ├── Engine
          ├── Cooling System
          ├── Fuel System
          ├── Hydraulic System
          └── ...

Torque Drill TD900
    └── 500 Hour PM
          ├── Engine
          ├── Cooling System
          ├── Hydraulic System
          └── Additional 500-hour inspections
```

When creating a job card, copy the relevant template inspection items into the job card. This is important because **historical job cards must never change when someone later edits a PM template**.

---

# 15. Integration With the Existing Equipment Platform

The PM Job Card should connect directly to:

```text
Equipment
Employees
Projects / Locations
Inventory
Maintenance History
```

The relationship should approximately be:

```text
Equipment
   │
   ├── PM Job Cards
   │      │
   │      ├── Inspection Items
   │      ├── Parts Used ──────> Inventory
   │      ├── Technicians ─────> Employees
   │      └── Signatures
   │
   ├── Defects
   ├── Maintenance History
   └── PM Schedule
```

A completed card should therefore automatically become part of the equipment's maintenance history.

A defect discovered during PM should also be capable of generating a **Defect/Work Order**, rather than leaving important problems buried inside the remarks field.

---

## Final instruction to the coding AI

> Recreate the supplied Preventive Maintenance Job Card as a template-driven digital maintenance module. Preserve all fields, inspection systems, inspection tasks, service/defect control information, supervisor comments and the three-party sign-off shown in the reference.
>
> Build a user-friendly Form/Edit interface for technicians and a separate read-only **View Job Card** interface. The View interface must visually reproduce the supplied paper job card in A4 landscape format, including its dark navy section headers, bordered tables, inspection rows, PM Control header, Service & Defect Control section, Machine Release section, comments area and Technician/Supervisor/Operator signatures.
>
> The View must support printing and PDF generation and should hide application controls when printed.
>
> Do not hard-code the maintenance checklist into individual job cards. Implement reusable PM templates linked to equipment/equipment types and PM intervals. When a job card is created, snapshot the template inspection items into the job card so historical records remain unchanged if the template is later modified.
>
> Integrate job cards with Equipment, Employees, Inventory, Locations/Projects and Maintenance History. Parts consumed during maintenance should be capable of linking to inventory transactions, and defects identified during an inspection should be capable of generating corrective work orders.
>
> The finished workflow should be:
>
> `Equipment → Select PM Schedule → Create Job Card → Perform Inspection → Record Actions/Parts → Supervisor Review → Sign-Off → Release Machine → View/Print Job Card → Maintenance History.`
