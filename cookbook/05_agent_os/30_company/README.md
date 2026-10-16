# Company Products

Manage standing responsibilities with SQLite for development.
PostgreSQL is supported for production, with the same sync and async methods.

| File | What it teaches |
| --- | --- |
| `01_manage_products.py` | Create two owners' Products, list unscoped or by owner, soft-delete, inspect and restore. |

Run with the development environment:

```bash
.venv/bin/python cookbook/05_agent_os/30_company/01_manage_products.py
```

For HTTP access, configure `AgentOS(db=db, company=CompanyConfig())` using
`AgentOS` and `CompanyConfig` from `agno.os`. An explicit `CompanyConfig(db=...)`
overrides the OS database. Omitting Company leaves its routes and scopes absent.

The routes are `GET` and `POST /company/products`, `GET`, `PATCH` and
`DELETE /company/products/{id}`, and `POST /company/products/{id}/restore`.
Lists return `{data, meta}` with `limit` and `page`; reads accept
`include_deleted=true`. Restore requires `products:delete`, like deletion.
Read and create/update require `products:read` and `products:write` respectively.

`CompanyManager` takes a sync database; `AsyncCompanyManager` takes an async
database and exposes the same methods as coroutines. `list()` returns rows and
a total. `user_id=None` is unscoped; a string filters by owner before paging.
The HTTP layer derives ownership from authenticated identity. Reads are
company-wide for callers with the read scope. With isolation on, writes to
another owner's Product return 403. Unscoped callers with the write scope can
change every Product; admins bypass owner isolation.

## Work records

| File | Demonstrates |
| --- | --- |
| `02_manage_projects.py` | Product-contained Projects, owner filtering, explicit transitions, soft delete and restore. |
| `03_manage_tasks.py` | Backlog proposals, executor acceptance, frozen scope, rescoping, review and completion. |

Projects start `proposed` and move to `active`, then `done`. Tasks start
`backlog` and move through `ready`, `in_progress`, `in_review`, and `done`.
Either can be `cancelled` from any non-terminal state. Each transition takes
`target` and a non-empty `reason`; history is returned on the record. Tasks
may return to Backlog to clear acceptance and change scope, and In review may
return to In progress for revisions. Terminal states cannot transition.

The HTTP routes use `/company/projects` and `/company/tasks`, with the same
CRUD, paging, soft delete and restore conventions as Products, plus
`POST /{id}/transitions`. Task Ready requests include `executor_type` and
`executor_id`; the API applies the scheduler's caller run-permission check.
Acceptance also validates the executor against the registry. Direct Python callers
pass `registry=Registry(...)` to their Company manager.

Project and Task HTTP reads are company-wide for callers with the resource's
read scope, matching Products. Edits and transitions are collaborative: callers with the resource write
scope can update or transition another creator's work, even with user isolation
enabled. This includes cancellation and returning Tasks to Backlog. The creator
stays unchanged, and transition history records the acting caller. Ready still
requires the caller's executor run permission; accepted Tasks must return to
Backlog before editing. Delete and restore remain owner-scoped when user
isolation is enabled, with the existing admin bypass.
New work can use another owner's Product or Project, with the Task and
Project still required to belong to the same Product. Manager and storage
methods retain explicit owner filters for direct callers.


## Playbook and Product Manager

| File | Demonstrates |
| --- | --- |
| `04_manage_playbook.py` | Sync/async wiki namespaces, atomic page creation, version conflicts and the learning decision log without a model. |
| `05_product_manager.py` | Model resolution, a standalone Product Manager, bounded Company tools and explicit MCP publication without a model call. |

Each Product has a durable wiki namespace with `brief.md` (human direction) and
`status.md` (current work). A second namespace holds company context. Default
pages are created on first access and never reset. GET `/company/products/{id}/wiki`
lists pages; GET and PUT `/company/products/{id}/wiki/{path}` read and write them.
The company namespace has the same surface at `/company/wiki`. Writes require the
filesystem `expected_version` read with the page; zero means create only. Conflicts
return 409. Pages are Markdown and paths must be relative and normalized.

Wiki reads require `wiki:read`; writes require `wiki:write`. Product ownership
controls writes under isolation. Company pages are unowned shared documents, so
only unscoped callers (admins, or isolation disabled) can change them. Every caller
with read permission can read both namespaces. Company services use FileSystem;
its existing backend owns storage and version checks.

GET and POST `/company/decisions` use `decisions:read` and `decisions:write`.
Decisions are learning log entries in the `company` namespace, never a file.
Listings support text, agent, session and age filters plus standard paging.
The server stamps human identity; agents get identity from injected run context.
Automatic learning recall includes human and agent decisions across the company;
explicit searches can still filter by agent. The learning machine binds the agent
ID when supplying decision tools. Standalone CompanyTools and direct MCP calls
leave agent attribution unset. The log is append-only: later outcomes are new
entries that reference the original decision.

Product Manager uses `CompanyConfig(model=...)`, otherwise the first declared
registry model. If neither exists, its unavailable reason appears in diagnostics
and manual APIs still work. With OS Manager enabled it is an internal member;
otherwise it is a standalone agent. Its id is reserved and its tools stay out of
the registry. It proposes Projects and Backlog Tasks, edits owned proposals,
updates `status.md` with a version check, and logs decisions through its learning
machine. It has no acceptance, completion, owner, Sources or scheduler tools.

CompanyTools can be published explicitly with `MCPConfig(tools=[...])`, following
the existing MCP toolkit convention. Direct MCP calls have the same write fence.
The examples make no provider calls; they do not demonstrate live model quality.
Routines and Sources are described below.


## Execution and attention

| File | Demonstrates |
| --- | --- |
| `06_execute_tasks.py` | Durable execution, duplicate starts, ordinary run history and attention with no model call. |

`06_execute_tasks.py` starts an accepted workflow Task through its ordinary run
route and the durable queue, waits for In review, reads paged history and checks
attention. It makes no provider calls. Start PostgreSQL with
`./cookbook/scripts/run_pgvector.sh`, then run:

```bash
.venv/bin/python cookbook/05_agent_os/30_company/06_execute_tasks.py
COMPANY_DB=postgres .venv/bin/python cookbook/05_agent_os/30_company/06_execute_tasks.py
```

The default stores Company records and sessions in temporary SQLite, with a
PostgreSQL queue. `COMPANY_DB=postgres` uses PostgreSQL for both. The example
creates and removes its own database schema. `COMPANY_QUEUE_DB_URL` overrides
the local PostgreSQL URL. SQLite follows the queue's existing development
fallback; use PostgreSQL session storage for production attempt fencing.

POST `/company/tasks/{id}/runs` accepts `{"attempt": 1}` (the default). Repeating
that attempt returns the first run. A new attempt increments the number; after
success, first transition In review to In progress to request revisions. Each
Task retains one session. GET on the same route returns ordinary session runs
with `limit` and `page`. GET `/company/runs/{id}` reads an individual run and
POST `/company/runs/{id}/cancel` uses the executor's existing cancellation route.

Start rechecks the registry, `tasks:write`, `wiki:read` and the executor's run
permission. Registry-only executors receive their ordinary routes when Company
is enabled. Each executor needs a run database, and execution requires
`QueueConfig(durable=True)`. An existing session retains the normal run route's
ownership checks. Engineering executors cannot be started yet. Framework-reserved executors,
including Product Manager and OS Manager, cannot be accepted or started as
Task executors.

Executor input contains only the Task brief, its evidence and the current
company and Product wiki pages. Queue retries and restart recovery use the
existing queue policy. Results are saved on the Task; success moves it to
`in_review`. Failure leaves the Task visible with an error result. Executors
cannot acquire scheduler mutation authority.

GET `/company/attention?product_id=...` returns `proposals`, `in_review` and
`failed` counts using the Task list filters. Omitting Product counts all work.
Attention and run reads are company-wide with `tasks:read`; Task lists also
accept `failed=true`. Failed work means an In progress Task whose latest result
is an error. Cancelling, replanning, reaccepting or reviewing the Task clears it
from failed attention while preserving the result as history. `failed=false`
includes all other Tasks, including those with no result. Existing databases add the Task execution columns with
`MigrationManager(db).up(table_type="tasks")` (await this migration coroutine).


## Heartbeat

| File | Demonstrates |
| --- | --- |
| `07_heartbeat.py` | Code-declared Products, a reader Source, an Intake Skill, scheduler rows and duplicate-free scans without a model call. |

Declare `Product`, `Source` and `Routine` from `agno.company`, then pass
`CompanyConfig(products=[...])`. The same declarations work in OS configuration:

```yaml
company:
  products:
    - id: documentation
      name: Documentation
      purpose: Keep docs current
      sources:
        - type: markdown
          reference: /workspace/docs
          credential_ref: DOCS_ACCESS_TOKEN
      routines:
        - name: intake
          template: intake
          executor_type: agent
          executor_id: source-reader
          cron_expr: "0 9 * * 1-5"
```

The executor must already be registered. Give it `CompanyTools(db)` and
`load_routine_skills()` if it should use the bundled reader, Intake and Summary
tools. Enable the existing AgentOS scheduler and queue to run schedules; the
cookbook only creates and inspects them. Scheduling alone never grants acceptance.
The OS scheduler database owns Routine definitions/history even with a separate
Company database. `metadata.routine_ids` links them to Products.

The templates are packaged `SKILL.md` files under `agno/company/skills`, loaded
through `LocalSkills`. Source types are `git` (a local checkout), `markdown` (a
file or directory), and `website` (a single page). Optional `config.paths` limits
local reads to relative files. Workspace exclusions and path confinement apply;
credential references name environment variables, whose presence diagnostics
report without disclosing values. Source reads produce evidence with the run id,
a SHA-256 hash of reader content, and a link. Task deduplication is per Product,
including completed and soft-deleted proposals. Failed reads create no proposals.

`/company/routines` wraps the scheduler. Writes require both `routines:write`
and `schedules:write`; histories require `routines:read` and `schedules:read`.
Pause/resume use scheduler disable/enable. Sources use `sources:read`,
`sources:write` and `sources:delete`, with Product ownership on writes.
`POST /company/setup` uses `products:write` to seed a blank deployment; nested
Sources and Routines also require their own write permissions. Retries and
restarts retain existing edits and do not restore archived records.

Summary uses Product metadata such as
`{"summary": {"interface": "slack", "destination": "C012345"}}` and the matching
interface configured on AgentOS. Pass those interfaces to `CompanyTools` for
custom executors. The summary is written to the Product wiki before delivery;
a transport failure remains a failed run with the report retained. Provider
retry guarantees still apply if a process dies after sending but before recording
success. No live messages are sent by this cookbook.

Existing Task tables need the shared migration:
`await MigrationManager(db).up(table_type="tasks")`. No Company-private storage
or migration machinery is used. Automatic acceptance is opt-in as described below.


## Automation

With Company, `scheduler=True`, and the durable queue configured, the scheduler
creates one managed `Company automation` schedule. Each minute it checks Ready
Tasks and authorized Routine proposals. It uses the scheduler's ordinary claims,
release, and run history. No extra loop, table, or route is installed. Skipped
Tasks and proposals have their reasons in this schedule's run output, readable
through `/schedules/{id}/runs`.

Run both behaviors without a model call:

```bash
COMPANY_AUTOMATION=1 .venv/bin/python cookbook/05_agent_os/30_company/06_execute_tasks.py
COMPANY_AUTOMATION=1 COMPANY_DB=postgres .venv/bin/python cookbook/05_agent_os/30_company/06_execute_tasks.py
```

The example advances the existing schedule's due time to avoid a one-minute
wait. The poller still claims the schedule, and Tasks still enter the ordinary
executor run route and durable queue. A pending submission retains its original
attempt on restart. The queue owns execution retry limits; new ticks do not
start additional attempts for running or failed Tasks. A human can request a
retry using the existing run route. Returning queued work to Backlog prevents
its executor from starting. Successful work remains In review.

An authenticated human needs `routines:write`, `schedules:write`, `tasks:write`,
and run permission for both the Routine target and the proposed Task executor.
POST `/company/routines` accepts `auto_accept` at creation; PATCH
`/company/routines/{id}` can authorize, edit, or revoke it. For example, replace
the IDs below with real records and PATCH this body:

```json
{
  "auto_accept": {
    "executor_type": "agent",
    "executor_id": "writer",
    "source_ids": ["release-notes"],
    "work_scope": {
      "product_ids": ["documentation"],
      "project_ids": ["release-documentation"]
    },
    "required_checks": ["project_active", "has_source_evidence", "executor_registered"],
    "limits": {"max_acceptances": 5, "expires_at": 1798761600}
  }
}
```

Every authorization names an exact executor type and ID. A proposal must name
that same executor, belong to the Routine's Product, and carry the framework's
Routine origin. `propose_company_task` and `intake_company_source` can name a
proposed executor and Project; neither can accept work. Source IDs, work scope,
and required checks are optional bounds. Omitted Source/scope bounds impose no
additional restriction; an empty allowed-ID list permits no matching work.
`project_ids` can include `null` to allow independent Tasks. Unknown fields and
check names fail closed. A Source bound requires verified reader evidence.

| Built-in required check | Server-side fact checked |
| --- | --- |
| `project_active` | The proposal's Project exists, belongs to the same Product, and is active. Independent Tasks fail this check. |
| `has_source_evidence` | Evidence names an existing Source in this Product; a fresh read through its configured reader matches each content hash and link. An asserted hash or `passed` field is insufficient. |
| `executor_registered` | The proposed executor exists in the current registry and passes the ordinary Company executor checks. Registry validation is also mandatory for every acceptance and dispatch. |

`limits.max_acceptances` defaults to **1** and counts successful automatic
acceptances over the Routine's lifetime, including archived Tasks and repeat
acceptances of the same Task. Editing the policy or restarting does not reset
that count. Raising the limit requires a new human authorization.
`limits.expires_at` is an optional UTC epoch-second expiry. The existing Product
row serializes acceptance accounting on SQLite and PostgreSQL; concurrent ticks
cannot exceed the limit.

Applications can add checks with
`CompanyConfig(acceptance_checks={"custom_check": callable})`. Every built-in
and custom callable has the same `(task, manager)` signature: a copy of the
proposal and the sync or async Company manager for the configured database.
A callable may be sync or async and must return exactly `True` to pass. Errors,
false results, and missing names keep the proposal in Backlog. Built-in names
cannot be overridden. Registration is application code, never a Routine payload
or agent tool operation.

PATCH `{"auto_accept": false}` to revoke. Every tick reloads the schedule,
checks the saved human's current authority using the scheduler's authorization
conventions, and repeats the checks before acceptance. Changed or revoked
policies also block already accepted automatic work at dispatch and in the
queue. Human acceptance snapshots use the same scheduler convention: stored-role
changes are re-evaluated; token-scope grants retain their saved scopes. Tasks
accepted before snapshots were introduced need fresh acceptance before pickup.
A disabled human cannot authorize automatic work through the user directory.

In a local deployment with authentication disabled, API callers are trusted
operators, as for the existing scheduler. Code/YAML declarations remain
proposal-only: write an automatic authorization through the human API.
Executors and Product Manager retain no `schedules:write` or SchedulerTools.
Private authorization is removed from public payloads and executor input;
Routine metadata is data, never a source of broader executor authority.
