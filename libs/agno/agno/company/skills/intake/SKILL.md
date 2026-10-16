---
name: intake
description: Inspect configured Sources and propose evidence-backed Backlog work.
---

Read the Product identified in the message and list its Sources and existing Tasks.
Use read_company_source to inspect evidence, then decide whether it supports
actionable work. Reading or changing a file alone is not a reason for a Task.
For each useful proposal, call intake_company_source with a concise title and
brief, the selected evidence_links, and a stable Source-local proposal_key for
the underlying issue. Reuse that key across scans, file edits and wording changes.
The tool verifies the links, attaches this run id and the reader's content hashes,
and durably deduplicates within the Product. Never copy entire documents into
briefs, manufacture evidence, or retry with a new key to bypass deduplication.
A failed read must not produce a proposal. Existing and completed Tasks remain
unchanged. Proposals stay in Backlog; never accept or complete work.
If all evidence is already recorded, return a quiet successful check.
