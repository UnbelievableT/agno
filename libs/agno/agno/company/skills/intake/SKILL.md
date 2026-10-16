---
name: intake
description: Inspect configured Sources and propose evidence-backed Backlog work.
---

Read the Product identified by product_id in run metadata and list its Sources.
Use intake_company_source for each configured Source. That tool reads first,
attaches this run id, content hash and link, and durably deduplicates each
proposal within the Product. Never manufacture evidence or retry with a new key.
A failed read must not produce a proposal. Existing and completed Tasks remain
unchanged. Proposals stay in Backlog; never accept or complete work.
If all evidence is already recorded, return a quiet successful check.
