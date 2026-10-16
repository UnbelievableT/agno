---
name: refresh
description: Refresh Product status from current work and source evidence.
---

Read the Product identified by product_id in run metadata. Read its playbook,
Projects and Tasks, then inspect configured Sources with read_company_source.
Reflect observed progress and failures in status.md using its current version.
On a conflict, read again and incorporate intervening changes. Propose changes
for human review; never accept work or mark a Task Ready or Done.
If nothing changed, return a quiet successful check without writing duplicate pages.
