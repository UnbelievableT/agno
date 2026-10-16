# Test Log: Company Products

## Heartbeat verification — October 16, 2026

### Final initial-schema verification

**Status:** PASS

**Description:** Incorporated PR 4's rebase onto main and initial-schema cleanup
through `309ab2e94decb310852b6c373a557695b6ef979b` using normal merge commits.
Company is unreleased, so execution and Heartbeat fields remain in the initial
Task schema; the draft migrations were removed. Fresh custom Task-table tests
cover execution/evidence fields, Routine provenance and deduplication identity.

**Result:** Complete database/OS/scheduler unit suites: **6,282 passed,
39 conditional skips** for optional drivers, root or live credentials.
Company/scheduler integrations plus the inherited filesystem transaction
regressions: **346 passed, no skips** (313 Company/scheduler and 33 filesystem).
All seven Company cookbooks passed again, and execution also passed with
PostgreSQL Company storage. Format and validation passed; the complete output
was read, including mypy success on 1,153 framework files and 21 CLI files.
No live model or outbound messages were used. The temporary MongoDB container
was removed after testing; existing PostgreSQL and Redis services were retained.

---

### Latest execution-base verification

**Status:** PASS

**Description:** Merged execution branch head
`41e7a104b48e891c2a53518589d6d8f677fddd5f` with a normal merge commit,
retaining both execution and Heartbeat regression tests. Reran every Company
cookbook and the PostgreSQL execution variant, all Company/scheduler integrations,
and the complete database/OS/scheduler unit suites. A temporary localhost-only
MongoDB container supported the existing Mongo unit and scheduler tests.

**Result:** Full unit rerun: **6,270 passed, 47 conditional skips**. Final
integrations: **261 passed, no skips**, including every SQLite/PostgreSQL case
and scheduler MongoDB lifecycle parity. Focused Task/Heartbeat/provenance checks:
**169 passed**; the subsequent setup identity regression passed all **10**
Heartbeat route tests. Setup retries retain the original Product even after
additional Products are created. All seven cookbooks and the extra PostgreSQL
execution run passed. Format and validation passed, with both mypy results read.
No live model or outbound messaging calls were made.

---

### Required regression suites

**Status:** PASS

**Description:** Ran the complete `libs/agno/tests/unit/db`,
`libs/agno/tests/unit/os` and `libs/agno/tests/unit/scheduler` suites, plus
all Company and scheduler database/OS integrations. Used Python 3.12 with
temporary optional dependencies; PostgreSQL integrations used the local
database on port 5532 and isolated schemas. The final setup ownership change
also passed the focused Heartbeat route/storage suite (35 tests).

**Result:** Unit suites: **6,270 passed, 47 skipped**. Conditional skips require
optional Firestore/Mongo/MySQL/asyncpg drivers, Redis, root, or a live OpenAI
credential. Company/scheduler integrations: **241 passed, 4 skipped**; only
MongoDB lifecycle cases skipped. All SQLite/PostgreSQL integration cases ran.
Compilation, `./scripts/format.sh` and `./scripts/validate.sh` passed; validation
output was read, including successful mypy checks on 1,155 framework files
and 21 CLI files. Validation used the clean Python 3.10 environment.

---

### 01_manage_products.py, 02_manage_projects.py, 03_manage_tasks.py

**Status:** PASS

**Description:** Ran all three files in `cookbook/05_agent_os/30_company/`
with the Python 3.12 development environment and SQLite after adding Sources
and scheduler-backed Routines.

**Result:** Product isolation, soft deletion/restoration, Project lifecycle,
and Task acceptance protection all passed without model calls.

---

### 04_manage_playbook.py, 05_product_manager.py

**Status:** PASS

**Description:** Ran both files in `cookbook/05_agent_os/30_company/`.
The playbook exercised sync/async wiki writes and stale-version rejection.
Product Manager exercised its bounded tools with trusted caller context.

**Result:** Wiki, Backlog proposals, status and decisions persisted. No model
or external messaging service was called.

---

### 06_execute_tasks.py

**Status:** PASS

**Description:** Ran `cookbook/05_agent_os/30_company/06_execute_tasks.py`
with default SQLite Company storage and again with `COMPANY_DB=postgres`.
Both used the local PostgreSQL durable queue and real application lifespan.

**Result:** The workflow reached In review; the duplicate start returned the
original run, and attention reported one In review item. Workers shut down
cleanly and removed temporary schemas. No model calls were made.

---

### 07_heartbeat.py

**Status:** PASS

**Description:** Ran `cookbook/05_agent_os/30_company/07_heartbeat.py`.
Startup rehydrated a declared Product, Markdown Source and Intake Routine.
Repeated reader evidence returned the original Backlog Task. The example
checked scheduler provenance, payload metadata, Product schedule ids and pause.

**Result:** All assertions passed. The Routine is an ordinary scheduler row
with `auto_accept=false`; no model or external message was sent.

---

### 01_manage_products.py

**Status:** PASS

**Description:** Ran `cookbook/05_agent_os/30_company/01_manage_products.py`
with the development environment on October 15, 2026, after simplifying the
internal scope-map handoff (SQLAlchemy 2.0.54). SQLite persistence,
two users, unscoped and owner-filtered listings, soft delete, include_deleted,
and restore were exercised.

**Result:** All assertions passed. Output:

```text
Isolation off: 2 Products
Isolation on for alice: 1 Product
Soft delete, include_deleted and restore passed
```

---


### 02_manage_projects.py

**Status:** PASS

**Description:** Ran `cookbook/05_agent_os/30_company/02_manage_projects.py`
on October 15, 2026 using SQLite and the development environment. Tested two
owners, unscoped and scoped listing, reasoned Project transitions, status
filtering, soft delete and restore without a model.

**Result:** All assertions passed; output: `Company projects lifecycle passed`.

---

### 03_manage_tasks.py

**Status:** PASS

**Description:** Ran `cookbook/05_agent_os/30_company/03_manage_tasks.py`
on October 15, 2026 using SQLite and the development environment. Tested
Backlog creation, executor and acceptor recording, frozen scope, returning to
Backlog and clearing acceptance, review/completion, filtering, delete and
restore. This example manages records without executing a model.

**Result:** All assertions passed. Output:

```text
Accepted scope is protected
Company tasks lifecycle passed
```

---

The existing `01_manage_products.py` was also rerun successfully with its
original output and assertions unchanged.


### Rebase verification: all Company examples

**Status:** PASS

**Description:** Reran `01_manage_products.py`, `02_manage_projects.py`, and
`03_manage_tasks.py` on October 15, 2026 after rebasing onto Products commit
`850ebb87a6a78c73392fd3c0a998ce9c18f8a823`, including its database shutdown
and async configuration reconstruction fixes. The new Project/Task inserts
also use the same required-row return convention as Products.

**Result:** All assertions passed. Products reported two unscoped records,
one Alice-owned record, and successful archive/restore checks. Projects
reported lifecycle success. Tasks reported protected accepted scope and
lifecycle success.

---


### Company-wide work reads

**Status:** PASS

**Description:** Reran all three cookbook files after rebasing onto Products
commit `c9ec5af77fb229a291dea1148eeb445331d1013d` and adopting its shared-read
behavior for Projects and Tasks. The direct manager examples retain explicit
owner filters.

**Result:** All cookbook assertions passed. The Company router and integration
run also passed 260 tests, including company-wide reads, paginated status
filters, shared Product/Project assignment, and owner-scoped writes and
transitions across sync/async SQLite and PostgreSQL.

---

### 02_manage_projects.py — collaborative HTTP edits and transitions follow-up

**Status:** PASS

**Description:** Reran the Project cookbook after allowing resource-authorized callers to edit and transition another creator's Project through HTTP.

**Result:** `Company projects lifecycle passed`. The cookbook checks direct-manager lifecycle, owner filtering, deletion, and restoration; separate HTTP regressions verify collaboration.

---

### 03_manage_tasks.py — collaborative HTTP edits and transitions follow-up

**Status:** PASS

**Description:** Reran the Task cookbook after allowing resource-authorized callers to edit Backlog Tasks and perform lifecycle transitions through HTTP.

**Result:** `Accepted scope is protected` and `Company tasks lifecycle passed`. Separate HTTP regressions verify cross-user acceptance, cancellation, returning to Backlog, attribution, and executor authorization.

---

## Playbook and Product Manager delivery

### 01_manage_products.py, 02_manage_projects.py, 03_manage_tasks.py

**Status:** PASS

**Description:** Reran all three existing files in `cookbook/05_agent_os/30_company/`
with the development environment on October 15, 2026. Products, Projects and
Tasks retain their owner filters, transitions, soft deletion and restoration.

**Result:** Each file completed successfully; accepted Task scope remained protected.

---

### 04_manage_playbook.py

**Status:** PASS

**Description:** Ran `cookbook/05_agent_os/30_company/04_manage_playbook.py` on
SQLite, sync and async. Created Product and company wiki namespaces, updated
status with its version, rejected a stale edit and saved learning decisions.

**Result:** Both paths completed without a model or provider credentials.

---

### 05_product_manager.py

**Status:** PASS

**Description:** Ran `cookbook/05_agent_os/30_company/05_product_manager.py`.
Configured a standalone Product Manager using the registry model, configured
explicit MCP toolkit publication, and called the bounded tools with trusted
application run context.

**Result:** Backlog proposal, status and decision persisted with the caller's
identity. No model call was made; live provider behavior was not tested.

---


### Final merged-base verification — October 16, 2026

**Status:** PASS

**Description:** Reran every file in `cookbook/05_agent_os/30_company/`:
`01_manage_products.py`, `02_manage_projects.py`, `03_manage_tasks.py`,
`04_manage_playbook.py`, and `05_product_manager.py`. All completed successfully
on the final implementation. The tested PR 2 head and merged main commit
`a88f7a518c61c2d8a76b4407ed7c1d07378b77fe` have identical Git trees; PR 3
was rebased onto that merge before publication.

**Result:** Products and Projects passed lifecycle checks; Tasks protected
accepted scope. Sync/async wiki edits rejected stale versions and persisted
learning decisions. Product Manager's bounded tools saved a caller-owned
Backlog proposal, status and decision. No provider calls were made.

The full database and AgentOS unit suites passed **6,079 tests**, with **15
conditional skips**. Company SQLite/PostgreSQL integrations (sync and async)
and filesystem integrations passed **238 tests**, with no skips. Shared
filesystem/context unit tests plus the new four-adapter parity tests passed
**840 tests** (overlapping the integration count). Format and validation passed,
including both mypy checks; the validate output was read.

---


### Review fixes — October 16, 2026

**Status:** PASS

**Description:** Reran all five files in `cookbook/05_agent_os/30_company/`:
`01_manage_products.py`, `02_manage_projects.py`, `03_manage_tasks.py`,
`04_manage_playbook.py`, and `05_product_manager.py`, after fixing Company
decision recall, tool instructions, author attribution and wiki routing.

**Result:** All cookbook assertions passed. The shared Company decision context
includes human entries; direct CompanyTools/MCP calls no longer claim Product
Manager authorship. Actual offline sync/async Product Manager runs verified
human decision context and the exposed tool names in system prompts.
The broader regression run passed **1,516 tests**, with no skips, covering
Company routes/tools, scopes, manager composition, diagnostics, learning,
context providers, and Company SQLite/PostgreSQL storage in both execution
modes. All provider calls remained offline. The original full database/OS
unit-suite results above precede this follow-up; those full suites were not
rerun for these focused fixes. Format and validation passed.

---


### Async filesystem transaction review — October 16, 2026

**Status:** PASS

**Description:** Reran `01_manage_products.py`, `02_manage_projects.py`,
`03_manage_tasks.py`, `04_manage_playbook.py`, and `05_product_manager.py`
after fixing async SQLite outer transaction ownership.

**Result:** All five cookbooks passed. Product/Project/Task lifecycle checks,
sync/async wiki version conflicts, and bounded Product Manager proposal, status
and decision writes passed. No provider calls were made.

The focused filesystem review reproduced four failing cases: exception and
cancellation after savepoint release persisted an async SQLite write on both
file-backed and in-memory databases. Explicit outer BEGIN fixes all four while
respecting caller-managed transaction hooks. The 33 new regression cases cover
legacy migrations (missing/nullable user column), data and partition retention,
partial DDL rollback, migration cancellation, partial-move rollback, cold-create
cancellation and retry, and durable connection recovery after cancellation.
All 33 passed on Python 3.10 and Python 3.12 with SQLite and PostgreSQL.

Filesystem/context units and filesystem/Company integrations passed **1,082
tests**, with no skips (includes the 33 cases above). Format and validation
passed; all validation output, including both mypy summaries, was read.
In-memory SQLite remains connection-owned: driver cancellation that invalidates
its only connection discards the database; durable cancellation recovery is
verified on file-backed SQLite and PostgreSQL.

---

Final full-suite rerun after this fix: **6,085 passed, 15 skipped** across
`libs/agno/tests/unit/db` and `libs/agno/tests/unit/os`. The temporary MongoDB
container was removed after the run; existing PostgreSQL services were retained.


### Execution and attention — October 16, 2026

**Status:** PASS

**Description:** Reran `01_manage_products.py`, `02_manage_projects.py`,
`03_manage_tasks.py`, `04_manage_playbook.py` and `05_product_manager.py` from
`cookbook/05_agent_os/30_company/` using the development environment after
merging Playbook fixes at `769eee4306558569988b346a8bd71dc9b945b700`.
The Task cookbook now supplies its executor registry at acceptance.

**Result:** Every existing assertion passed. Products/Projects/Tasks retain their
lifecycle behavior; wiki edits reject stale versions; Product Manager tools
persist proposals, status and decisions. No model calls were made.

---

### 06_execute_tasks.py

**Status:** PASS

**Description:** Ran `cookbook/05_agent_os/30_company/06_execute_tasks.py` twice:
default SQLite Company/session storage with a PostgreSQL durable queue, and
`COMPANY_DB=postgres` for PostgreSQL Company/session/queue storage. The real
application lifespan starts the queue worker. A registered workflow receives
only brief/wiki/evidence, executes an accepted Task, and persists its result.

**Result:** Both runs reached In review, returned the original run for the
repeated attempt, and listed one ordinary run in the Task session. Attention
returned `{"proposals": 0, "in_review": 1, "failed": 0}`. Both workers shut down
cleanly and the example removed its temporary schema. SQLite emitted the
existing warning that its session fallback does not provide PostgreSQL's
attempt fencing. No provider calls were made.

---

### Execution regression checks — October 16, 2026

**Status:** PASS

**Description:** Ran the complete `libs/agno/tests/unit/db` and
`libs/agno/tests/unit/os` suites, all Company database integrations, and the
final execution authorization/error-handling tests. Tests use temporary SQLite
files and isolated PostgreSQL schemas with offline model fixtures.

**Result:** Full unit suites: **6,095 passed, 15 skipped**. Company integrations:
**175 passed**, no skips, across sync/async SQLite and PostgreSQL. Final execution
route tests: **13 passed** (10 overlap the full suite). These include the final
503 response when Company storage is absent and 404 for deleted Product context
without reserving a run. Format and validation passed, including both mypy
checks, and all validation output was read. Validation used the clean Python
3.10 environment; tests and cookbooks used the Python 3.12 development environment.

---

### Execution review fixes — October 16, 2026

**Status:** PASS

**Description:** Reproduced rejected input consuming a Task attempt and
`failed=false` omitting pending Tasks whose result is JSON null. All 16 new
regression cases failed before the fix across sync/async SQLite and PostgreSQL;
input rejection was checked for agents, teams and workflows. The existing run
validator now checks input before reservation, and nonfailed filters include
null extracted result statuses.

**Result:** Execution, Task router/isolation and Task storage regressions passed
**197 tests**, including all 16 new cases. Rejected input leaves Ready and its
transition history intact; correcting the executor schema allows attempt 1 to
complete. Pending and unstarted Tasks both appear in nonfailed counts before
pagination; failed Tasks appear only in the failed filter. Reran
`cookbook/05_agent_os/30_company/06_execute_tasks.py` with SQLite and with
`COMPANY_DB=postgres`: both passed through the real durable worker, returning
the first run on duplicate start and reporting one Task In review. No provider
calls were made. Format and validation passed and their output was read.
The full unit-suite result above predates these focused review fixes.

---

### Automation cookbook regression — October 16, 2026

**Status:** PASS

**Description:** Ran all seven files in `cookbook/05_agent_os/30_company/`
with the Python 3.12 development environment:

- `01_manage_products.py`: Product CRUD and lifecycle assertions passed.
- `02_manage_projects.py`: Project lifecycle and Product ownership assertions passed.
- `03_manage_tasks.py`: Task acceptance and lifecycle assertions passed.
- `04_manage_playbook.py`: wiki persistence and version-conflict checks passed.
- `05_product_manager.py`: proposal, status, and decision tools passed.
- `06_execute_tasks.py`: manual start passed on SQLite and PostgreSQL.
- `07_heartbeat.py`: Routine, Source, and rehydration assertions passed.

**Result:** Ten executions passed, including two additional runs of
`06_execute_tasks.py` with `COMPANY_AUTOMATION=1`, once with SQLite Company
storage and once with `COMPANY_DB=postgres`. Both used the real PostgreSQL
durable queue and application scheduler lifespan. A human-accepted Ready Task
was picked up without a start request; a Routine proposal with verified Source
evidence was automatically accepted using the built-in `has_source_evidence`
and `executor_registered` checks, then executed to In review. The example
revoked the authorization and cleaned up its temporary schema. No application
check registration, provider calls, or external messages were needed. SQLite
retains its documented development-only session fallback.

---

### Attention lifecycle and reserved executors — October 16, 2026

**Status:** PASS

**Description:** Added 56 cases: failure attention after cancellation, Backlog,
reacceptance, review and completion; all four framework-reserved executor IDs
at acceptance/start on all four SQL adapters; and reserved-ID exclusion during
registry mounting. The initial run reproduced 38 failures, with 18 existing
reserved-specialist protections already passing. Failed/nonfailed predicates
now partition Tasks by active error state while retaining SQL/JSON null handling.

**Result:** **253 targeted tests passed**, including all 56 new cases and the
previous review regressions. Per-Product and company-wide attention clear handled
failures, pagination totals remain correct, and error results remain intact as
history. Product Manager and OS Manager are rejected explicitly even with a
custom registry resolver. Reran `06_execute_tasks.py` with SQLite and
`COMPANY_DB=postgres`; both completed with one Task In review. Format and
validation passed, including both mypy checks, and their output was read. No
provider calls were made. The earlier full unit-suite result remains the baseline.

---

### Automation final validation — October 16, 2026

**Status:** PASS

**Description:** Validated Automation with Heartbeat head
`c1f7f0b1909c9660e755b26e298650b99ee480b7` incorporated. The full
`libs/agno/tests/unit/db`, `libs/agno/tests/unit/os`, and
`libs/agno/tests/unit/scheduler` suites passed **6,312 tests**. Fifteen
conditional skips cover optional Firestore/Mongo/MySQL test dependencies, a
root-only test, live OpenAI tests, and Redis-only stream-fencing tests.

**Result:** All Company and scheduler database integration files passed
**359 tests** on sync/async SQLite and PostgreSQL. Four optional MongoDB
scheduler cases were skipped; no requested SQLite/PostgreSQL cases were skipped.
The scheduler HTTP owner-recheck integration file passed **6 tests**. The ten
cookbook executions listed above were rerun successfully on the merged code.
Compilation, the full format script, and validation passed; both mypy summaries
(1,155 Agno files, 21 agnoctl files) and the full validation output were read.
Unrelated formatter changes were excluded and validation passed again on the
exact feature tree. Tests/cookbooks used Python 3.12 and validation used the
clean Python 3.10 development environment.

Regressions cover two concurrent claims, interrupted dispatch before and after
queue submission, queued withdrawal, executor mismatch, revoked authorization,
built-in checks without application registration, unknown checks with recorded
reasons, forged Source evidence, scope/check races, and lifetime limits.
Payload authority injection and internal-token-only Task submission are denied.
Self-review reproduced a Routine Project proposal regression on all four
adapters; its fix and the complete integration rerun passed. No live provider
calls or outbound messages were made.

---

### Rebase onto merged Playbook — October 16, 2026

**Status:** PASS

**Description:** Rebased PR 4 onto `main` at
`f801d7c7421e7a7da5d6cee42fd4b0b8bceabe98`, including the final Playbook async
filesystem transaction fixes. Preserved both branches' test-log entries during
the sole conflict. Commit and tree comparisons confirmed the execution changes
were preserved and the inherited filesystem code matches main.

**Result:** **286 targeted tests passed**: Company execution/Task regressions
plus the 33 filesystem transaction cases from the merged base. All six Company
cookbooks passed, and execution also passed with PostgreSQL session storage.
Format and validation passed; both mypy checks and all script output were read.
No provider calls were made. The full unit-suite figures above remain their
historical baseline; this rebase used focused regression coverage.

---

### Initial Task schema — October 16, 2026

**Status:** PASS

**Description:** Removed the Company execution migration and its version
registration because Company tables have not been released. Execution references,
evidence and results remain part of the initial Task schema. Replaced the upgrade
test with fresh custom-table creation and execution checks on sync/async SQLite
and PostgreSQL. Restored the unrelated migration unit tests to their main versions.

**Result:** **186 targeted tests passed**, covering execution, authorization,
fresh Task schema/index creation and the restored migration suites. Both
execution cookbook modes passed. Format and validation passed (mypy: 1,146 core
files and 21 CLI files), and all output was read. No provider calls were made.
Earlier migration test entries describe the implementation before this simplification.

---
