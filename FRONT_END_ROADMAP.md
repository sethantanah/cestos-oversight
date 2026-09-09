I studied the OpenAPI specification as a **product**, not just as a collection of endpoints. The backend is already large enough that the frontend should not be built page-by-page according to endpoint names. It needs to be organized around **real operational workflows**.

The specification currently exposes **289 API paths**, with particularly deep coverage for Inventory, Equipment, Workforce/HR, Projects, Clients and Locations. Inventory alone contains the full lifecycle around stock, requests, receipts, issues, transfers, reservations, stock counts, adjustments, reconciliation, forecasting, imports/exports and reporting. Equipment similarly contains assignments, status/location history, meters, components, documents, inspections, defects, insurance, registrations and media. 

There are also aggregation endpoints that should strongly influence the frontend architecture instead of forcing the browser to assemble everything itself—for example, project overviews already return the client, project manager, sites, employee and asset counts, current employees/assets and recent assignment history.  Asset capabilities similarly include assignments and meter readings, while inspections carry condition, defects and follow-up state.  

# Frontend product model

I would make the application feel like an **operations command system**, with this mental model:

```text
                           CESTOS OPERATIONS

                                 HOME
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
          WORKFORCE            PROJECTS             EQUIPMENT
              │                    │                    │
              └──────────────┬─────┴─────┬──────────────┘
                             │           │
                         INVENTORY   OPERATIONS
                             │
                    ┌────────┼─────────┐
                    │        │         │
                  STORES   STOCK    MOVEMENTS
                    │        │         │
                    └────────┴─────────┘
                             │
                         REPORTING

                              +
                           ADMIN
```

The user should rarely think in terms of database objects. They should think:

> I need to assign Samuel to Project Alpha.

> I need to transfer Rig CDR-003.

> I need to issue filters to that rig.

> I need to receive new stock.

> I need to approve a request.

> I need to see what is happening at Project Alpha.

That philosophy should control the frontend.

---

# 1. Main application shell

Use a fixed desktop sidebar with a compact mobile/tablet alternative.

The main navigation should be:

```text
Cestos Operations

Dashboard

Projects
Workforce
Equipment
Inventory

Operations

Reports

────────────

My Workspace
Notifications

────────────

Administration
Settings
```

Inventory should expand:

```text
Inventory
    Overview
    Items
    Stores
    Requests
    Receipts
    Issues
    Transfers
    Returns
    Reservations
    Stock Counts
    Adjustments
    Transactions
    Forecast & Reorder
    Reports
```

Workforce should expand:

```text
Workforce
    Overview
    Employees
    Availability
    Rotations
    Leave
    Training & Compliance
    Documents
```

Equipment:

```text
Equipment
    Fleet Overview
    Assets
    Available Equipment
    Inspections
    Defects
    Compliance
```

Projects:

```text
Projects
    All Projects
    Clients
    Locations
```

Do not show everything to everyone.

Navigation should be **permission-aware**.

For example, a Storekeeper could primarily see:

```text
Dashboard
Inventory
    Stock
    Requests
    Receipts
    Issues
    Transfers
    Counts
My Workspace
```

while the CEO sees the entire operational picture.

The API already contains dedicated access endpoints for Equipment, Inventory and HR, so these should be used together with the authenticated user's information to drive frontend capabilities rather than merely hiding buttons cosmetically. 

---

# 2. Authentication flow

The frontend authentication layer should be implemented before any business modules.

Flow:

```text
Login
   ↓
POST /auth/login
   ↓
Access Token + Refresh Token
   ↓
GET /auth/me
   ↓
Load User
   ↓
Load Domain Access
   ├─ HR access
   ├─ Equipment access
   └─ Inventory access
   ↓
Build Allowed Navigation
   ↓
Dashboard
```

The client should automatically refresh expired access tokens using the refresh endpoint. If refresh fails:

```text
clear session
→ redirect to login
→ preserve intended URL
```

After reauthentication, return the user to that URL if permitted.

Do not scatter authentication handling across screens. Use a centralized HTTP/API client.

---

# 3. Global application dashboard

The `/operations/summary` endpoint should power the first version of the main landing page.

But it should not just be a wall of KPI cards.

Design:

```text
Good morning, Seth

Cestos Operations                           Sep 9, 2026
────────────────────────────────────────────────────────

ACTIVE PROJECTS      ACTIVE EMPLOYEES      OPERATING ASSETS
      6                     147                    18

AVAILABLE PEOPLE     AVAILABLE ASSETS       BREAKDOWNS
     12                       4                     2

────────────────────────────────────────────────────────

Needs Attention

⚠ 2 critical equipment defects
⚠ 7 employee documents expiring
⚠ 4 equipment registrations expiring
⚠ 11 inventory items below critical stock
⚠ 6 inventory requests pending approval

────────────────────────────────────────────────────────

Projects

Project Alpha       ACTIVE       42 people     6 assets
Project Bravo       ACTIVE       31 people     4 assets
Project Delta       MOBILIZING   18 people     3 assets

────────────────────────────────────────────────────────

Recent Activity

09:32  Rig CDR-002 transferred to Project Alpha
09:18  200 L Hydraulic Oil received at Main Warehouse
08:51  Employee assigned to Project Bravo
08:34  Inventory request approved
```

Some cross-domain "needs attention" cards will require parallel requests initially.

Later the backend can expose one CEO dashboard endpoint.

---

# 4. Universal UI patterns

This matters because you have hundreds of endpoints.

Do not invent a unique interaction style for every domain.

Use four main patterns.

### Entity list

Used for:

```text
Employees
Projects
Assets
Inventory Items
Clients
Stores
Suppliers
```

Structure:

```text
Title                     Search        Filters       + Create

[Quick status chips]

──────────────────────────────────────────────────────────────
ID          Name          Status      Location       ...
──────────────────────────────────────────────────────────────
...
```

Filters should be URL/query based.

Example:

```text
/assets?status=BREAKDOWN&project_id=...
```

This makes links bookmarkable and preserves filters on back navigation.

### Entity command page

Used for:

```text
Employee
Asset
Project
Inventory Item
Store
```

Structure:

```text
Identity Header
        ↓
Important Status/KPIs
        ↓
Primary Actions
        ↓
Tabs
```

### Workflow document

Used for:

```text
Inventory Request
Receipt
Issue
Transfer
Stock Count
Adjustment
```

These are not ordinary CRUD forms.

They are **state machines**.

The page needs to communicate:

```text
DRAFT → SUBMITTED → APPROVED → POSTED
```

or:

```text
DRAFT → APPROVED → DISPATCHED → IN TRANSIT → RECEIVED
```

Actions should appear according to state.

### Action drawer/modal

Use side drawers for small actions:

```text
Assign Employee
Record Meter
Change Asset Status
Add Family Member
Add Skill
Approve Request
Reject Request
```

Use full pages for complex multi-line transactions:

```text
Create Inventory Receipt
Create Inventory Issue
Create Transfer
Stock Count
Create Employee
Create Asset
```

---

# 5. Workforce frontend

The API supports far more than a normal employee directory. It includes employee filtering and availability, a workforce dashboard, full and overview profiles, family and emergency contacts, resumes, documents, qualifications, skills, training, licences, rotations, asset authorization, time logs, leave and transfers. 

The frontend therefore needs to treat Workforce as a full module.

## Workforce overview

Route:

```text
/workforce
```

Use:

```text
GET /employees/dashboard-summary
GET /rotations/upcoming
GET /training/expiring
GET /employee-licenses/expiring
GET /employee-documents/expiring
```

Screen:

```text
WORKFORCE

Employees       Assigned       Available       Off Rotation
   184             146             18               12

────────────────────────────────────────────────────────

Employees by Department        Employees by Project
[chart]                        [chart]

────────────────────────────────────────────────────────

Upcoming Rotations

Employee          Project         Change        Date
Samuel Doe        Alpha           Off site      Sep 12
James Toe         Bravo           Return        Sep 13

────────────────────────────────────────────────────────

Compliance Attention

7 Licences Expiring
5 Training Certifications Expiring
4 Documents Expiring
```

## Employees directory

Route:

```text
/workforce/employees
```

Use the extensive filters already provided by `/employees`, including department, position, status, availability, project, location, supervisor, skill, licence type, rotation state and document/contract expiry. 

Important quick filters:

```text
All
Available
Assigned
On Leave
Off Rotation
Unassigned
Inactive
```

Clicking an employee opens:

```text
/workforce/employees/:id
```

## Employee 360

Header:

```text
[PHOTO]

Samuel Doe
EMP-000143

Senior Driller • Drilling

ACTIVE              ASSIGNED

Project Alpha
Alpha Site

[Edit] [Transfer] [More]
```

Overview tab should primarily consume:

```text
GET /employees/{id}/overview
```

because that endpoint is designed for aggregation.

Tabs:

```text
Overview
Employment
Assignments
Family
Emergency
Resume
Documents
Qualifications
Skills
Training
Licences
Rotations
Equipment Authorization
Time
Leave
Activity
```

Sensitive tabs should not even render without appropriate access.

## Employee creation

Use a multi-step wizard rather than displaying every employee field at once.

```text
1 Personal Details
       ↓
2 Employment
       ↓
3 Contact & Address
       ↓
4 Department / Position / Supervisor
       ↓
5 Review
       ↓
Create Employee
```

After creation:

```text
Employee created
        ↓
Employee profile
        ↓
"Complete employee setup"
```

Checklist:

```text
○ Profile photo
○ Emergency contact
○ Next of kin
○ Resume
○ Employment contract
○ Qualifications
○ Skills
○ Licences
○ Training
○ Project assignment
```

This prevents a monstrous employee form.

## Assignment flow

From employee profile:

```text
Assign to Project
      ↓
Select Project
      ↓
Select Site
      ↓
Role / Position
      ↓
Supervisor
      ↓
Start Date
      ↓
Rotation Pattern
      ↓
Review
      ↓
Assign
```

Transfer should be a separate explicit action:

```text
Current:
Project Alpha

Transfer To:
[Project Bravo]

Effective Date
Site
Role
Supervisor
Rotation

[Transfer Employee]
```

Backend already exposes an employee transfer action, so don't emulate transfers through manual assignment edits.

## Family and emergency contact flow

Family card:

```text
Family

Jane Doe           Spouse       Next of Kin
Samuel Jr.         Child        Dependant
Anna Doe           Child        Dependant

+ Add Family Member
```

Emergency section:

```text
PRIMARY
Jane Doe
Spouse
+231 ...

Secondary
Michael Doe
Brother
+231 ...
```

Actions:

```text
Set Primary
Edit
Archive
```

## CV and documents

Resume:

```text
Current Resume
Samuel_Doe_CV_2026.pdf
Uploaded Sep 3, 2026

[View] [Download] [Upload New Version]

History
v3 Current
v2
v1
```

Documents:

```text
Passport           VERIFIED     Expires Jun 2028
Driver Licence     WARNING      Expires Oct 2026
Safety Certificate VERIFIED     Expires May 2027
```

Use status chips and expiry severity.

---

# 6. Employee self-service portal

This should be distinctly different from the HR administration screens.

The backend exposes `/hr/me`, self-managed emergency contacts, time logs, leave requests, leave attachments and contract download. 

Route:

```text
/my
```

Employee home:

```text
MY WORKSPACE

My Profile
Current Assignment
Rotation
Time Logs
Leave
Documents / Contract
Emergency Contacts
```

Leave flow:

```text
Request Leave
    ↓
Start Date
End Date
Reason
Optional Supporting Letter
    ↓
Submit
    ↓
PENDING
```

Manager/HR sees pending leave elsewhere.

Employee sees:

```text
Annual Leave
Sep 20 - Sep 26
PENDING
```

This is preferable to giving ordinary employees access to the administrative Employee module.

---

# 7. Projects module

Projects should be one of the strongest cross-domain pages because the backend already gives a rich project overview. It includes client, manager, sites, employee count, asset count, current employees, current assets and recent assignments. 

## Project list

```text
/projects
```

Cards or table:

```text
PRJ-001
Project Alpha
Client: ...
ACTIVE

42 Employees
6 Assets

[Open]
```

Quick filter:

```text
All
Planning
Mobilizing
Active
Paused
Completed
```

## Project command center

```text
/projects/:id
```

Header:

```text
PROJECT ALPHA
PRJ-001

Client: Bea Mining
Project Manager: ...
Status: ACTIVE

Start: ...
Target Metres: ...

[Edit Project]
```

Tabs:

```text
Overview
Sites
Workforce
Equipment
Inventory
Activity
```

Overview:

```text
WORKFORCE               EQUIPMENT
42 assigned             6 assigned

SITES
3

───────────────────────────────────

Current Workforce
...

Current Equipment
...

Recent Assignment Activity
...
```

Project inventory tab should use:

```text
/projects/{id}/inventory-summary
```

Project equipment tab:

```text
/projects/{id}/equipment-summary
```

Manpower:

```text
/projects/{id}/manpower-summary
```

This gives the project manager one cohesive view instead of making them navigate among five modules.

---

# 8. Equipment module

The Equipment UI should feel like a **fleet command center**, not an equipment database.

There are endpoints for fleet availability and dashboarding, project equipment summaries, assignment/transfer actions, meters and reset, components, documents, insurance, registration, ownership, media, inspections, defects, location/status histories and activity.  

## Fleet dashboard

```text
/equipment
```

Screen:

```text
FLEET

TOTAL      OPERATING      AVAILABLE      STANDBY
  31          19              4              3

BREAKDOWN       MAINTENANCE       OUT OF SERVICE
    2                2                   1

─────────────────────────────────────────────────────

Needs Attention

2 Critical Defects
3 Insurance Expiring
4 Registrations Expiring
6 Stale Meter Readings

─────────────────────────────────────────────────────

Fleet by Project

Alpha       7
Bravo       5
Delta       4

─────────────────────────────────────────────────────

Asset Status

CDR-001      OPERATING      Alpha
CDR-002      BREAKDOWN      Bravo
PU-003       AVAILABLE      Main Yard
```

## Asset list

Filters:

```text
category
status
project
location
ownership
operator
responsible employee
availability
```

Use strong status coloration, but do not rely on color alone.

## Asset 360 page

Route:

```text
/equipment/assets/:id
```

Header:

```text
[PRIMARY PHOTO]

CDR-003
AST-000023
Diamond Drill Rig

OPERATING        ELIGIBLE

Project Alpha
Alpha Site

8,423.4 ENGINE HOURS

[Record Meter]
[Inspect]
[Transfer]
[Change Status]
```

Tabs:

```text
Overview
Assignments
Meters
Components
Inspections
Defects
Documents
Insurance
Registration
Ownership
Media
Location History
Status History
Inventory Consumption
Activity
```

## Record meter interaction

Use a small drawer:

```text
Current
8,423.4 h

New Reading
[________]

Recorded At
[________]

Source
[Manual]

Evidence Photo
[optional]

[Record]
```

If new meter < current meter:

```text
This reading is lower than the latest recorded value.

Normal meter readings cannot decrease.

[Cancel]
[Record as correction/reset]  ← only with permission
```

## Inspection flow

```text
Inspect Asset
     ↓
Inspection Type
     ↓
Condition
     ↓
Meter
     ↓
Defects Found?  YES / NO
     ↓
If YES:
Describe defect
Follow-up required?
     ↓
Save
```

If condition is `UNSAFE` or severe defect is found, UI should immediately surface:

```text
Asset requires attention

[Report Defect]
[Change Status to Out of Service]
```

Don't silently perform those secondary actions unless the backend explicitly supports a combined workflow.

## Transfer flow

```text
CDR-003

Current
Project Alpha
Alpha Site

─────────────────────

Transfer To
Project Bravo

Location
Bravo Drill Site

Responsible Employee
...

Primary Operator
...

Current Meter
8423.4

Effective
...

[Transfer]
```

After success:

```text
Transferred successfully.

View Project Bravo
View Assignment History
```

---

# 9. Inventory — this should be the largest frontend module

The API already supports a very complete inventory lifecycle, including stock, transactions, reconciliation, forecast, item/store overviews, categories, units, suppliers, conversions, stock policies, compatibility, receipts, issues, returns, transfers, requests, adjustments, stock counts, reservations, lots, serials, custody, reports, imports and exports.  

Do **not** put 15 equal menu entries in front of users without workflow prioritization.

## Inventory home

```text
/inventory
```

Top should answer:

```text
What needs my attention?
What happened recently?
How much stock do we have?
What is about to run out?
```

Screen:

```text
INVENTORY

Inventory Value     Low Stock     Out of Stock     Critical
  $428,500             43             11               7

Pending Requests     In Transit     Quarantined     Reorder
      12                 8              5             28

──────────────────────────────────────────────────────

ACTION REQUIRED

CRITICAL
Oil Filter
14 remaining • 12 days estimated
Lead time 21 days
[View] [Reorder]

LOW STOCK
Hydraulic Oil
...

──────────────────────────────────────────────────────

Recent Movements

09:41   RECEIPT     Engine Oil       +800 L    Main Warehouse
09:30   ISSUE       Filter            -2 pcs   Rig CDR-002
08:55   TRANSFER    Hydraulic Oil    200 L     Alpha → Bravo

──────────────────────────────────────────────────────

Consumption by Project

[chart]

Inventory Value by Category

[chart]
```

## Inventory items

Route:

```text
/inventory/items
```

Important columns:

```text
Item
SKU / Item No.
Category
Total Stock
Available
Reserved
Reorder Status
Est. Days Remaining
```

Quick chips:

```text
All
Low Stock
Out of Stock
Critical
Expiring
Slow Moving
Dead Stock
```

## Item 360

```text
/inventory/items/:id
```

Header:

```text
ITM-000143
Hydraulic Oil ISO 46

Lubricants
HIGH CRITICALITY

2,480 L ON HAND
2,180 L AVAILABLE

Reorder Status: WARNING
Estimated Remaining: 26 days
```

Tabs:

```text
Overview
Stock by Store
Movements
Consumption
Lots / Serials
Suppliers
Compatibility
Forecast
Activity
```

Stock distribution:

```text
Main Warehouse             1,400 L
Alpha Project Store          580 L
Bravo Project Store          500 L
```

This should allow a user to click a store and drill into its stock.

---

# 10. Inventory Request flow

This is the beginning of most internal inventory consumption.

```text
Project / Employee
        ↓
Create Request
        ↓
DRAFT
        ↓
Add Items
        ↓
Submit
        ↓
PENDING APPROVAL
        ↓
Approve / Reject
        ↓
APPROVED
        ↓
Create Issue
        ↓
Storekeeper fulfills
        ↓
POSTED
```

UI should show a workflow header:

```text
REQ-000143

✓ Draft
✓ Submitted
● Awaiting Approval
○ Issue
○ Fulfilled
```

Request creation should be optimized for adding multiple items:

```text
Request Inventory

Project
[Project Alpha]

Asset
[CDR-003 - optional]

Needed By
[date]

Priority
[Normal]

Purpose
[Maintenance]

────────────────────────────

ITEM                    AVAILABLE       REQUEST
Oil Filter                 12              2
Engine Oil                400 L           20 L

+ Add Item
```

After approval:

```text
[Create Issue]
```

Use the existing create-issue-from-request endpoint rather than asking the storekeeper to recreate the document manually.

---

# 11. Inventory Receipt flow

```text
Supplier delivery
      ↓
Create Receipt
      ↓
Choose Store
      ↓
Add items
      ↓
Lots / Serial / Expiry if needed
      ↓
Save Draft
      ↓
Review
      ↓
POST
      ↓
Stock increases
```

The page should clearly distinguish:

```text
SAVE DRAFT
```

from:

```text
POST RECEIPT
```

Posting is a consequential operation.

Use confirmation:

```text
Post Receipt REC-000145?

This will add:

800 L Engine Oil
24 Oil Filters
10 Fuel Filters

to Main Warehouse.

Posted stock movements cannot be freely edited.

[Cancel] [Post Receipt]
```

---

# 12. Inventory Issue flow

This should be exceptionally fast for storekeepers.

```text
Create Issue

Issue From
Main Warehouse

Issue To
Project Alpha

Asset
CDR-001 (optional)

Received By
Samuel Doe

Purpose
Maintenance

────────────────────────────────────

Search / Scan Item

Engine Oil
Available: 420 L
Issue: 20 L

Oil Filter
Available: 14
Issue: 2

────────────────────────────────────

[Save Draft]        [Post Issue]
```

When selecting an item, display:

```text
AVAILABLE AT THIS STORE
```

not company-wide stock.

If stock is insufficient:

```text
Requested: 20
Available: 14

Insufficient available stock.

Other locations:
Project Bravo Store      31
Main Workshop             8

[Create Transfer]
```

That cross-link makes the system far more useful.

---

# 13. Inventory Transfer flow

This should visually model movement between stores.

```text
TRANSFER TRF-00124

Main Warehouse
      ↓
Project Alpha Store

Items
...

DRAFT
```

After approval:

```text
APPROVED

[Dispatch]
```

When dispatched:

```text
IN TRANSIT

Dispatched:
Sep 9, 10:42

From:
Main Warehouse

To:
Project Alpha Store

[Receive Transfer]
```

Destination stock should not appear as available until receipt.

The API explicitly supports the sequence `approve → dispatch → receive`, so the frontend should make this state progression very clear rather than presenting generic Edit buttons. 

---

# 14. Returns

Return should preferably start from the original issue:

```text
Issue ISS-00211
       ↓
[Return Items]
       ↓
Select items/quantity
       ↓
Condition
   ├ Good
   ├ Used serviceable
   ├ Damaged
   ├ Defective
   └ Quarantine
       ↓
Post Return
```

If damaged:

```text
Returned quantity will be placed in quarantine and will not become available stock.

[Confirm]
```

---

# 15. Stock count flow

This needs its own focused workspace.

```text
COUNT-00031
Main Warehouse

DRAFT
   ↓
START
   ↓
IN PROGRESS
   ↓
SUBMIT
   ↓
APPROVE
   ↓
POST
```

During count:

```text
Item                    System       Counted       Variance

Engine Oil              hidden?      [_______]       —
Oil Filter              hidden?      [_______]       —
Fuel Filter             hidden?      [_______]       —
```

Consider optional **blind count mode** later, where the physical counter does not see system quantity.

After submit:

```text
VARIANCE REVIEW

Engine Oil
System: 480 L
Counted: 475 L
Variance: -5 L

Oil Filter
System: 14
Counted: 14
Variance: 0
```

Approval then posting creates the inventory correction.

---

# 16. Adjustments

Never present adjustment as "Edit stock."

Use:

```text
New Stock Adjustment
```

and force:

```text
Store
Item
Current System Quantity
Adjustment
Reason
Notes
```

Then:

```text
PENDING APPROVAL
```

Large or sensitive adjustments should visually indicate their consequence.

---

# 17. Inventory transaction ledger

Route:

```text
/inventory/transactions
```

This is the forensic screen.

Columns:

```text
Date
Transaction
Type
Item
Quantity
From
To
Project
Asset
Employee
Reference
Status
```

Click transaction → side panel/full record.

For users with permission:

```text
[Reverse Transaction]
```

Reversal dialog:

```text
You are reversing a posted inventory transaction.

The original transaction will remain in history.
An opposite ledger entry will be created.

Reason *
[______________________]

[Cancel] [Reverse Transaction]
```

---

# 18. Inventory forecast & reorder center

Route:

```text
/inventory/planning
```

Use:

```text
/forecast
/reorder-recommendations
/low-stock
/critical-stock
/out-of-stock
```

Screen:

```text
INVENTORY PLANNING

Item            Available    Usage/day    Days Left    Lead Time    Action

Oil Filter         14           1.2          12          21        REORDER
Engine Oil        480 L        22 L          21          14        WATCH
Drill Bit          3            .3           10          30        CRITICAL
```

Quick toggle:

```text
Reorder Required
Critical
Low Stock
All Forecast
```

Do not make a user open individual item pages to discover stockout risk.

---

# 19. Store command center

Route:

```text
/inventory/stores/:id
```

Screen:

```text
MAIN WAREHOUSE

Stock Value
Items
Low Stock
Pending Requests
Incoming Transfers
Outgoing Transfers

[Receive Stock]
[Issue Stock]
[Transfer Stock]
[Start Count]

──────────────────────────────────────

Stock
Transactions
Requests
Transfers
Counts
Bins
```

This page will probably become the storekeeper's main workspace.

---

# 20. Inventory import flow

Your API already has preview and confirm endpoints for imports. 

Design:

```text
Import Inventory

1 Select Import Type
    Items
    Opening Stock
    Stock Policies

2 Upload CSV/XLSX

3 Validation Preview

Row  Result
1    ✓
2    ✓
3    ERROR: Unknown unit "bttl"
4    ERROR: duplicate SKU

4 Confirm Import
```

Never send the user directly from file upload to import completion.

The preview endpoint should drive this.

---

# 21. Reports

Do not have users navigate raw `/reports/{kind}` concepts.

Create a report center:

```text
/reports
```

Cards:

```text
Inventory
    Stock on Hand
    Stock Valuation
    Movement Ledger
    Consumption
    Low Stock
    Dead Stock
    Aging

Workforce
    Employee Register
    Availability
    Compliance
    Rotation

Equipment
    Fleet Status
    Defects
    Expiring Compliance
    Assignment History

Projects
    Project Resource Summary
```

Where export endpoints exist, display:

```text
[Export CSV]
```

preserving current filters.

---

# 22. Notifications and approvals

The HR APIs already expose notifications and email-delivery management, while Inventory has multiple approval states.

I would create a global top-bar inbox:

```text
🔔 8
```

Click:

```text
Needs Your Attention

Inventory Request
REQ-00123
Project Alpha
5 minutes ago
[Review]

Leave Request
Samuel Doe
Today
[Review]

Asset Defect
CDR-003
CRITICAL
[Open Asset]
```

Eventually this should become cross-domain.

For MVP, combine available notification endpoints with client-side links to relevant domain queues.

---

# 23. Global search

Add a command/search box:

```text
Search Cestos...
```

Search should eventually understand:

```text
EMP-00123
Samuel Doe
CDR-003
AST-00013
Project Alpha
ITM-00331
Oil Filter
```

Your APIs already expose several domain-level search and lookup capabilities, including specialized equipment and inventory lookup endpoints. 

Initial implementation can federate a few requests.

Later create one backend global-search endpoint.

---

# 24. Cross-domain navigation is critical

This is where the frontend can make the system feel much more intelligent than independent CRUD modules.

Every entity reference should be clickable.

For example:

```text
Inventory Issue

Project Alpha     → click → Project page

CDR-003           → click → Asset page

Samuel Doe        → click → Employee page

Oil Filter        → click → Inventory Item page

Main Warehouse    → click → Store page
```

Likewise Asset → Inventory Consumption should let me click the transaction or item.

Project → Employee should open employee.

Employee → Current Project should open project.

This is the heart of the **connected operational system**.

---

# 25. Frontend technical architecture

If the frontend hasn't already been locked to another stack, I would use:

```text
React + TypeScript

React Router
or Next.js App Router if already using Next

TanStack Query
    server state
    caching
    mutations
    invalidation

React Hook Form
    complex forms

Zod
    client-side form schemas

A component system
    Shadcn / Radix style primitives
    or the project's existing UI library

Generated OpenAPI types/client
    where practical
```

The most important architectural separation should be:

```text
UI Components
      ↓
Domain Hooks
      ↓
API Services
      ↓
Generated / Typed API Client
      ↓
FastAPI
```

Avoid:

```text
React component
   ↓
raw fetch("/api/...")
```

scattered across 150 components.

---

# 26. Recommended frontend directory model

```text
src/

app/
    router
    providers
    auth
    layout

api/
    client
    generated
    errors
    auth-interceptor

components/
    ui
    data-table
    forms
    status
    dialogs
    files
    charts
    entity-links

features/

    dashboard/

    workforce/
        employees/
        assignments/
        family/
        documents/
        training/
        rotations/
        leave/

    projects/

    equipment/
        assets/
        assignments/
        meters/
        inspections/
        defects/

    inventory/
        items/
        stores/
        receipts/
        issues/
        requests/
        transfers/
        returns/
        adjustments/
        stock-counts/
        transactions/
        forecast/
        reports/

    administration/

lib/
    permissions
    dates
    money
    query-params
    downloads
```

Organize frontend code by **business feature**, not HTTP resource type.

---

# 27. Query and cache strategy

Treat list/detail queries consistently.

Example query keys:

```text
["employees", filters]

["employee", employeeId]

["employee-overview", employeeId]

["assets", filters]

["asset-overview", assetId]

["inventory-items", filters]

["inventory-item-overview", itemId]

["inventory-transactions", filters]
```

After an employee assignment:

```text
invalidate employee overview
invalidate employee assignments
invalidate employee list
invalidate project overview
invalidate workforce dashboard
```

After inventory issue posting:

```text
invalidate issue
invalidate item stock
invalidate store stock
invalidate inventory dashboard
invalidate transaction ledger
invalidate project inventory
invalidate asset inventory consumption
```

These invalidation rules should live next to domain mutations rather than being improvised inside screens.

---

# 28. Status-aware action system

Do not show impossible actions.

Example Inventory Transfer:

```text
DRAFT
Edit
Submit/Approve
Cancel

APPROVED
Dispatch
Cancel

IN_TRANSIT
Receive

RECEIVED
View only
```

Example employee assignment:

```text
ACTIVE
Transfer
Complete

COMPLETED
View only
```

Example asset:

```text
AVAILABLE
Assign

OPERATING
Record Meter
Inspect
Transfer
Change Status

BREAKDOWN
Inspect
View Defects
```

This makes the frontend mirror backend business rules.

---

# 29. Forms should be context-aware

A form should not ask for irrelevant information.

Inventory Issue:

If:

```text
purpose = ASSET_CONSUMPTION
```

then require/show:

```text
Asset
Project
Received By
```

If:

```text
purpose = PPE
```

prioritize:

```text
Employee
```

If asset selected:

```text
Project should auto-populate from current asset assignment
```

where possible.

Likewise an equipment transfer selecting Project Alpha should restrict Site to Project Alpha locations.

This is where the frontend can substantially reduce bad data.

---

# 30. Empty states

Do not render empty tables with "No records."

Examples:

```text
No family members added

Add spouse, children, dependants or next-of-kin information to complete this employee's profile.

[Add Family Member]
```

```text
No meter reading recorded

Recording the first meter reading allows equipment usage and future maintenance intervals to be tracked.

[Record Meter]
```

```text
No stock at this store

Receive or transfer inventory into this location.

[Receive Stock] [Create Transfer]
```

---

# 31. Mobile and field workflow

A full management dashboard can remain desktop-first.

But several operational actions should be excellent on mobile:

```text
Record Asset Meter
Inspect Equipment
Report Defect
Inventory Lookup
Issue Stock
Receive Transfer
Stock Count
Employee Time Log
Leave Request
```

These need:

large controls,
minimal typing,
camera/file upload,
QR/barcode-ready lookup,
good loading/error recovery.

The frontend architecture should not assume every user sits at an office PC.

---

# 32. Error UX

Translate backend errors into operational language.

Bad:

```text
422 Unprocessable Entity
```

Good:

```text
Cannot issue 25 Oil Filters.

Available stock at Main Warehouse is 14.
```

Bad:

```text
409 Conflict
```

Good:

```text
CDR-003 already has an active assignment to Project Alpha.

Complete or transfer the current assignment first.
```

Preserve backend error details for developers, but users should see domain language.

---

# 33. Loading behaviour

Use skeletons for full-page initial loads.

For mutations:

```text
button → loading state → success → refresh dependent data
```

Don't blank the entire page after every action.

For lists, preserve the previous data while filters/pagination fetch.

---

# 34. Frontend execution sequence

I would implement the frontend in this exact order:

| Phase   | Scope                                                                            | Why                                                             |
| ------- | -------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| **F1**  | App shell, auth, permissions, API client, errors, tables/forms/status components | Everything depends on it                                        |
| **F2**  | Main dashboard + Projects                                                        | Establish the cross-domain navigation center                    |
| **F3**  | Workforce + Employee 360 + self-service                                          | Mature API surface and core organizational data                 |
| **F4**  | Equipment + Asset 360                                                            | Establish fleet operations                                      |
| **F5**  | Inventory item/store foundation                                                  | Items, stores, stock, lookup                                    |
| **F6**  | Inventory operational flows                                                      | Request → Issue, Receipt, Transfer, Return                      |
| **F7**  | Stock controls                                                                   | Counts, adjustments, reservations, ledger, reconciliation       |
| **F8**  | Inventory intelligence                                                           | Forecast, reorder, aging, slow/dead stock, reports              |
| **F9**  | Cross-domain polish                                                              | Project ↔ employee ↔ asset ↔ inventory navigation               |
| **F10** | Mobile/field optimization                                                        | Fast field workflows                                            |
| **F11** | UX hardening                                                                     | permissions, loading, concurrency/error handling, accessibility |
| **F12** | E2E acceptance tests                                                             | Complete operational scenarios                                  |

---

# 35. The most important end-to-end frontend acceptance test

Before considering the frontend complete, one manager should be able to do this without ever feeling like they are switching between unrelated applications:

```text
Create Client
      ↓
Create Project
      ↓
Create Project Site
      ↓
Open Project
      ↓
Assign Employees
      ↓
Assign Drill Rig
      ↓
Open Rig
      ↓
Record Meter
      ↓
Inspect Rig
      ↓
Report Defect
      ↓
Open Inventory
      ↓
Request Part
      ↓
Approve Request
      ↓
Issue Part
      ↓
Link issue to Rig + Project + Employee
      ↓
Open Rig again
      ↓
See inventory consumption
      ↓
Open Project
      ↓
See workforce + equipment + inventory together
```

And an HR workflow should work as:

```text
Create Employee
      ↓
Add Family
      ↓
Set Next of Kin
      ↓
Set Emergency Contact
      ↓
Upload Resume
      ↓
Upload Documents
      ↓
Add Qualifications
      ↓
Add Skills
      ↓
Add Licences
      ↓
Assign Project
      ↓
Set Rotation
      ↓
Employee logs in
      ↓
Views own profile
      ↓
Logs time
      ↓
Requests leave
```

And inventory:

```text
Receive 1,000 L Engine Oil
        ↓
Main Warehouse = 1,000
        ↓
Transfer 300 → Project Alpha
        ↓
Dispatch → 300 In Transit
        ↓
Receive → Alpha = 300
        ↓
Reserve 50
        ↓
Available = 250
        ↓
Issue 100 to CDR-001
        ↓
Return 20
        ↓
Perform Count
        ↓
Post variance
        ↓
Ledger reconciles
        ↓
Forecast updates
        ↓
Project and Asset consumption update
```

If those three stories feel smooth, the application is becoming an actual **Cestos operating system** rather than a frontend placed on top of an API.

## One backend gap I would account for

From the uploaded OpenAPI, the currently exposed product is heavily developed in **Workforce/HR, Equipment, Projects and Inventory**. I did not find equivalent top-level Maintenance, Fuel or Procurement endpoint groups in this version of the specification. So I would **not put empty Maintenance/Fuel/Procurement sections in the production navigation yet**. Build the frontend architecture so those modules can slot in later, but only expose modules that have functioning backend workflows. 

The strongest next move is therefore to begin the frontend with **F1: shell + authentication + permissions + API layer + reusable UX primitives**, because with almost 300 paths, getting that foundation right will determine whether the rest of the frontend stays manageable or becomes 200 independently coded screens.



BACKEND URL: https://cestos-oversight.fly.dev/"/api/v1   
API_SCHEMA: C:\Users\User\Documents\Projects\cestos\API_DATA.md
