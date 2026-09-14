---
name: operations-intelligence
description: >-
  Operational intelligence, dual-source SQL database telemetry querying, and FAISS document vector search guidelines for Cestos Smart Assistant.
  Use when querying workforce skills, employee resumes, fleet utilization, project targets, or document libraries.
---

# Cestos Operations Intelligence & Smart Assistant Skill Guide

This skill defines the query strategy, data mapping, and synthesis workflows for the Cestos Smart Assistant across live relational database telemetry (PostgreSQL / SQLite) and semantic vector search (FAISS embeddings).

---

## 1. Dual-Source Intelligence Architecture

The Cestos Smart Assistant evaluates user requests through two complementary data access layers:

```
                      +-----------------------------------+
                      |   User Query / Natural Prompt     |
                      +-----------------------------------+
                                        |
                  +---------------------+---------------------+
                  |                                           |
                  v                                           v
    +---------------------------+               +---------------------------+
    |  Structured SQL DB Query  |               |  FAISS Semantic Vector    |
    |    (Live Telemetry Tool)  |               |    (Document Store Tool)  |
    +---------------------------+               +---------------------------+
    | - Employee / Skill tables |               | - Employee Resumes / CVs  |
    | - Fleet & Asset status    |               | - Training Certificates   |
    | - Project & Drilling m    |               | - Standard Operating Proc |
    | - Inventory Stock values  |               | - Contracts & Policies    |
    +---------------------------+               +---------------------------+
                  |                                           |
                  +---------------------+---------------------+
                                        |
                                        v
                      +-----------------------------------+
                      |   Executive Synthesis Engine      |
                      |  (Zero-Hallucination Markdown)    |
                      +-----------------------------------+
```

---

## 2. Workforce & Skill Query Guidelines

When a user asks questions about employees, personnel qualifications, computer skills, job titles, or certifications:

### A. Structured SQL Queries
1. **Target Tables**:
   - `employees`: `first_name`, `last_name`, `job_title`, `department`, `employment_status`, `notes`, `bio`.
   - `employee_skills` & `skills`: `name`, `category`, `proficiency_level` (`BASIC`, `INTERMEDIATE`, `ADVANCED`, `EXPERT`, `CERTIFIED`).
   - `employee_qualifications`: `qualification_name`, `field_of_study`, `institution`.
   - `employee_licenses`: `license_type`, `license_number`.
2. **Search Term Matching**:
   - Extract core search keywords (e.g. `computer`, `python`, `rig operator`, `safety`, `geology`).
   - Execute case-insensitive partial string matching (`ILike`) across skill names, qualification fields, job titles, bios, and employee notes.

### B. Unstructured Vector Document Search
1. **Target Content**:
   - Employee Resumes (`CV`, `RESUME` document types in `LibraryDocument`).
   - Educational & Training Certificates.
2. **Search Strategy**:
   - Query FAISS vector index with prompt embeddings to find semantic matches (e.g. matching software skills mentioned in full CV text).
   - If vector index status is pending/indexing, fall back to metadata fuzzy matching on file names, document titles, and categories.
   - Surface relevant document chunks with file titles, locations, and direct snippet citations.

---

## 3. Operations & Fleet Query Guidelines

- **Fleet Utilization**: Aggregate `assets` by `status` (`OPERATING`, `AVAILABLE`, `UNDER_MAINTENANCE`, `BREAKDOWN`, `STANDBY`).
- **Drilling & Projects**: Aggregate `target_metres`, drilled meterage, and active project counts from `projects`.
- **Inventory Valuation**: Calculate total stock value by joining `inventory_items`, `inventory_categories`, and `inventory_balances`.

---

## 4. Synthesis & Response Formatting

1. **Zero-Hallucination Policy**: Every numerical count, monetary figure, skill match, or citation must be derived strictly from live DB context or vector results.
2. **Citation Requirement**: When document snippets or resumes are retrieved via vector search, cite the exact `document_title`, `file_name`, and relevance score.
3. **Personnel Presentation**: Present matching personnel clearly with name, job title, department, registered skill level, and any vector-surfaced resume evidence. Include clickable links to their profile or documents.

---

## 5. Direct Entity UUID Resolution & UI Route Matrix

When returning information about specific entities (employees, assets, inventory items, stores, projects, or documents), the Smart Assistant resolves entity primary keys (`id` UUIDs) and constructs direct deep-link routes that open entity detail modals and previews directly.

### A. Direct Entity Route Matrix
- **Employee Profiles & Personnel**:
  - Direct Detail Modal Link: `[Employee Name](/workspace/employees/{employee_id})`
  - Workforce Search Fallback: `[Search Workforce](/workspace/employees?search={employee_name})` or `[Workforce Overview](/workforce-overview)`
- **Fleet & Asset Equipment**:
  - Direct Asset Detail Link: `[Asset Name](/workspace/assets/{asset_id})`
  - Fleet Search Fallback: `[Search Fleet](/workspace/assets?search={asset_number})` or `[Fleet Dashboard](/fleet-dashboard)`
- **Inventory & Stores**:
  - Direct Item Detail Link: `[Item Name](/workspace/inventory/items/{item_id})` or `[Item Detail](/workspace/items/{item_id})`
  - Direct Store Detail Link: `[Store Name](/workspace/inventory/stores/{store_id})`
  - Stock Catalog Search: `[Search Catalog](/inventory-overview)`
- **Document Library & Resumes**:
  - Direct Document Reader Modal: `[Document Title](/documents?doc_id={document_id})`
  - Document Search Fallback: `[Search Document Library](/documents?q={document_file_name})`
- **Project Operations & Site Command**:
  - Direct Project Command Link: `[Project Name](/project-command-center?project={project_id})`
  - Project Portfolio Link: `[View Portfolio](/projects-overview)`

### B. Resolution & Link Formatting Rules
1. **Primary Key Resolution**: Always select entity `id` UUIDs in SQL DB telemetry and FAISS vector citations.
2. **Direct Links Primary**: Prefer direct UUID links (e.g. `[Seth Antanah](/workspace/employees/2e57ee87-e798-4e66-bcfa-55fbd8aa40c3)`) over text searches whenever the entity ID is known.
3. **Document Reader Trigger**: Use `/documents?doc_id={document_id}` so clicking a resume or certificate directly opens the in-app document text reader modal.
4. **External Tab Preservation**: The frontend Markdown engine automatically renders these links with `target="_blank"` and `window.open(url, '_blank')` so navigation opens in a new tab without interrupting the user's active Smart Assistant session.


