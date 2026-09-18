# CESTOS execution plan

Prepared 15 September 2026 from `NEXT_STEPS.md` and the current backend models, services, endpoints, and workflow documentation. This is an implementation proposal, not confirmation that every existing feature is deployed or production-verified. Frontend behavior described below follows the repository workflow documentation and needs verification during delivery.

## Recommendation

Extend the existing platform around **approved production by rig and shift, with traceable revenue and cost entries**. This unlocks the rig contribution equation and the company → project → rig → shift drilldown. Build the operating model first, then deliver this complete workflow on one pilot project before expanding into the full commercial, procurement, finance, and client-portal vision.

Keep the current FastAPI/PostgreSQL application and its organization, permission, audit, document, employee, asset, and inventory foundations. Introduce bounded modules inside it; no service split is needed for the initial rollout. FAISS remains a document retrieval system. Financial calculations must use structured, approved records in PostgreSQL.

## What we can reuse

| Area | Existing foundation | Extension needed |
|---|---|---|
| Projects | Portfolio dashboard, project register, command center, assignments/supervisors, sites, targets, updates and activity | Programs, individual drill holes, shifts, rig production, approvals, budgets and contribution |
| Equipment | Assets, assignments, meters, hierarchical components, inspections, defects and status history | Link failures, downtime, component repairs and cost lines into the existing maintenance workflow |
| Maintenance/fuel | Maintenance jobs with scheduling, recurrence, technician and total cost; fuel quantities and prices | Meter-based plans, detailed work orders, classified downtime, parts/labour costs and fuel reconciliation |
| Inventory | Suppliers, stores, issues/returns, requests, receipts, reservations, valuation ledger, stock policies and forecasts | Real PO/work-order relationships, procurement approvals, inspections and program-based forecasts |
| People | Employees, skills, qualifications, training, licences, rotations, assignments, equipment authorizations, time logs and salary records | Shift crew allocation, approved labour costing, reporting compliance and governed scorecards |
| Documents | Central catalog, ownership/privacy, tags, extraction, OCR, full-text and FAISS search | Register every new module's attachments, approval/version context and explicit client sharing |
| Management | Operational counts, attributed activity, notifications and internal operational intelligence | Defined metric sources, financial permission boundaries, threshold alerts and control-tower drilldowns |
| Commercial/finance/HSE | Clients, project contract number/value, safety-type reports and HR notifications | Commercial contracts/rates, opportunities, formal incidents/actions, cost subledger and accounting integration |

Important distinctions: a project contract value is not earned revenue; salary records are not posted payroll costs; asset status counts are not time-based utilization. Inventory already has a posting and valuation engine, so we should extend its links rather than create a competing stock ledger. The existing internal assistant is distinct from the proposed external mining-market intelligence workflow.

Evidence: `app/models/project.py`, `project_report.py`, `asset.py`, `asset_records.py`, `operational_logs.py`, `inventory.py`, `employee.py`, `hr.py`; `app/services/inventory_queries.py`; `app/api/v1/endpoints/intelligence.py`; and the existing project, dashboard and document workflow documents.

## Phase 0 — Operating model and delivery baseline

Produce the Master Operating Model requested in NEXT_STEPS: departments, process owners, approval chains, profit centres, data ownership, permissions and a metric dictionary. Operations owns production/time classification; maintenance owns faults and downtime; stores owns stock posting; HR owns attendance/rates; finance owns billing, costing, exchange rates and period closure; commercial owns opportunities/contracts; HSE owns incidents/actions.

Agree scheduled machine hours, billable versus productive time, standby rules, metre acceptance, reporting timezone, currency conversion, labour burden, overhead allocation, and correction policy. Define direct contribution separately from contribution after allocated overhead. Keep earned revenue, invoicing and cash collection separate.

Verify a clean production-like Linux build, locked dependencies, backend imports, migrations and representative access checks before further rollout. The recent startup failures make this a release gate. Confirm document-index persistence, backups and recovery, and benchmark OCR/indexing memory alongside API traffic.

**Exit:** signed-off definitions and approval matrix, selected pilot project/rigs, reconciled baseline data, and a reproducible deployment. Resolve accounting-system ownership here: preferably integrate the existing accounting source instead of implementing a general ledger.

## Phase 1 — Rig and shift production

Add drilling programs, identifiable drill holes, planned shifts, rig/crew allocations, production intervals and time segments. A shift can report work on multiple holes; record from/to depth, metres, core recovery where applicable, drilling method and relevant ground conditions. Capture productive, standby, maintenance and other nonproductive periods without overlapping machine time. Validate rig/project assignments and crew authorizations against effective dates.

Extend the command center with **Production**, retaining Updates for narrative, safety and site reports. A drilling update should link to detailed production and show its summary. Historical aggregate reports remain historical facts; do not invent their rig, shift or hole allocation. Explicitly prevent linked summaries and detailed production being added together.

Introduce Draft → Submitted → Approved/Returned. Preserve approved versions and use audited corrections rather than silently rewriting accepted work. Current report documentation calls reports immutable, but the API contains a patch route: align implementation and documentation as part of this change. Record submitter, approver, reporting time, effective work time, correction reason and evidence.

Start with retry-safe submissions and saved drafts; add offline synchronization if pilot connectivity requires it. Use idempotency keys and conflict handling to prevent duplicate production after retries.

**Exit:** one pilot project with two rigs can complete a full shift cycle, reconcile approved metres and hours, and drill down from project totals to the original report. Existing reports, attachments, assignments and activity continue to work.

## Phase 2 — Rig contribution and project costing

Introduce the minimum commercial foundation now: project contracts, effective-dated rate cards, depth/service bands, standby and mobilisation rules, approved billable quantities, and revenue entries. Full sales CRM can follow later.

Add an operational cost subledger with rig/project/shift dimensions, cost category, quantity, unit, original currency, conversion snapshot, source record/version, actor and approval state. Derive entries from existing inventory consumption, approved fuel records, maintenance parts/labour, approved employee time and effective loaded rates. Add controlled manual entries for logistics, camp, subcontractor and other direct costs. Keep unattributed costs visible in an unallocated bucket; use explicit allocation rules for shared costs.

One source transaction must post once. Returns and corrections reverse or adjust their original entries. A fuel issue and its fuel-use log must not create two expenses; neither should a parts issue and the work order containing it. Inventory purchases increase stock; consumption drives the relevant operating cost. Avoid adding a maintenance job's total again when its detailed cost lines are already posted.

Deliver **Costs & Revenue** inside project details and **Performance** inside rig details: revenue, direct cost, contribution, contribution percentage, cost/metre, litres/metre and target variance, with source drilldowns. Show provisional values, missing costs and unallocated amounts prominently. Zero denominators show unavailable, not a fabricated percentage.

**Exit:** finance reconciles a pilot period to source records, including a return, corrected report, shared expense and foreign-currency transaction. For a simple fixture, 100 accepted metres × $50 yields $5,000 revenue; $3,000 direct cost yields $2,000 contribution and 40%. This is not EBITDA or cash flow.

## Phase 3 — Maintenance reliability and formal HSE

Extend `AssetMaintenanceJob` into the work-order workflow, reusing components, inspections and defects. Connect inspection → defect/failure → work order → component → parts/labour → repair → downtime. Add calendar/meter triggers, failure taxonomy, cause/remedy, technician approvals and auditable meter history. Replace inventory's placeholder work-order links with validated relationships.

Calculate availability, classified downtime, maintenance cost/hour and repeat failures from recorded intervals and events. Define utilization and availability denominators in Phase 0; do not infer them from current status. Display estimated lost contribution as an estimate separate from actual booked repair costs.

Add formal incidents, near misses, corrective actions, responsible owners, deadlines and closure evidence. Existing safety reports can initiate these records. Implement missing-report, overdue maintenance, expiring authorization and overdue-action alerts with owners and acknowledgement.

**Exit:** an inspection fault can be repaired and closed with parts and downtime reconciled, without duplicate costs. An HSE action has a complete assignment-to-closure audit trail. This phase can run alongside Phase 2 once Phase 1 identifiers and time rules are stable.

## Phase 4 — Procurement and planning

Extend existing inventory requests and suppliers into request approval → RFQ → supplier comparison → purchase order → delivery/inspection → receipt → invoice match. Support partial deliveries, rejection/returns, approval limits and separation of requester/approver duties. Connect invoice/payment status to the chosen accounting system.

Retain existing stock policies and forecasts. Add program-based demand using planned metres, methods and validated consumption assumptions, with lead times, criticality and safety stock. Compare supplier prices only after normalizing units, currency and relevant landed costs.

**Exit:** one approved request can be traced through partial receipts and invoice matching to stock, consumption and project cost; planning flags a foreseeable shortage with its assumptions. Dependencies: Phase 2 cost rules and Phase 3 work-order links.

## Phase 5 — CEO control tower and supervisor scorecards

Expand the main dashboard progressively as each underlying module becomes trustworthy. Provide company → project → rig → shift/source navigation, date filters, currency basis, freshness, targets and provisional/closed-period labels. Start with production, availability, cost/metre and contribution. Add backlog, receivables, cash and EBITDA only when their commercial/accounting sources exist and reconcile.

Reuse notification infrastructure for an 08:00 local-time digest and actionable exceptions. Every alert needs a rule, source evidence, owner, deduplication and resolution state; display its reporting cutoff so incomplete morning data is understood.

Implement the proposed supervisor weights as configurable, versioned policy: production 25%, rig condition 20%, downtime 15%, HSE 15%, consumables 10%, crew management 5%, reporting 5%, stewardship 5%. Missing evidence must not silently score zero. Account for ground conditions, rig condition and factors outside supervisor control; provide human review and correction before performance consequences.

**Exit:** every displayed metric is reproducible from authorized source records, and a supervisor can see the evidence and policy behind their score. Initial operational tiles can ship in earlier phases; the complete tower depends on Phases 2–4 and commercial/accounting integration.

## Phase 6 — Commercial intelligence and client access

Extend Clients with opportunities, tender stages, quotations, probability, value, expected dates and contract renewal reminders. Basic opportunity tracking can run in parallel after Phase 0; integrate won deals with the contracts/rates introduced in Phase 2.

Add reviewed market signals with source URL/document, publication date, retrieval date, company/project matching, confidence and reviewer. Deduplicate and retain provenance. Start with approved/manual sources before automated collection; validate access rights and source terms. AI can summarize evidence and suggest opportunities, with human review before sales action. Unverified market claims in NEXT_STEPS are not implementation assumptions.

Build a separate client portal using external identities and explicit client/project grants. Publish approved progress, selected holes, photos, reports and invoice views through controlled sharing. Existing document PUBLIC means organization-visible, not client-visible. Preserve private and Super Private restrictions across downloads, previews, search and extracted text; require an explicit authorized publication workflow for client material.

**Exit:** a client sees only explicitly published material for its projects, including through search and direct file URLs. An opportunity is traceable to evidence, quotation, contract and project.

## Delivery mechanics and first increment

Use additive migrations and feature flags. Backfill only relationships supported by evidence; retain legacy totals and visibly distinguish incomplete attribution. Use unique source-posting keys, transactional audit entries, approval histories and defined period-close/reopen rules. Centralize metric calculations so dashboard, exports and assistant answers agree. Add targeted indexes on organization, project, rig, reporting time and status; introduce summary tables only where measured query cost warrants them.

Every phase includes API, UI, migrations, permissions, activity presentation, document registration, acceptance tests and a pilot walkthrough. Include cross-organization isolation, financial/HR access, correction/retry behavior and regression checks for existing workflows. AI retrieval must enforce the same permissions as ordinary reads, including salary and private document boundaries.

The first implementation increment should produce:

1. Operating-model document, metric dictionary, approval matrix and production schema/API design.
2. Reproducible deployment and migration baseline with the current features checked.
3. One rig-shift drilling form with hole intervals, crew, time classification and attachment.
4. Submission, supervisor approval and readable activity: names, project, rig, shift and changed values.
5. Approved production totals with source drilldown and legacy-report reconciliation.

Do not put the full procurement suite or complete CEO dashboard into this first increment. Its acceptance demonstration is a real shift entered, approved and reflected once in project/rig totals.

## Decisions and estimates

Before implementation, confirm the pilot project/rigs, billing rules, accounting software, approval limits, currencies, labour-cost access and site connectivity. The plan can proceed with these as Phase 0 decisions; none requires guessing historical data.

Indicative effort, assuming one dedicated backend engineer and one frontend engineer with regular operations/finance input: Phase 0, 1–2 weeks; Phase 1, 3–5; Phase 2, 4–6; Phase 3, 4–6; Phase 4, 4–6; Phase 5, 2–4; Phase 6, 5–8. These are rough planning ranges, not commitments. Parallel work requires additional capacity; integration, offline requirements, data cleanup and accounting scope can materially change them. Re-estimate after Phase 0 and after the pilot. A narrower useful production-and-contribution release is the first milestone, rather than waiting for the entire vision.
