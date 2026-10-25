# TopxAI Tests

Run on 2026-10-16 against `https://ai.topxea.com/v1` with a TopxAI key, model `kimi-k3`, macOS, Python 3.12.

### basic.py

**Status:** PASS (sync, sync streaming, async); see note for async streaming

**Description:** Basic TopxAI model cookbook covering sync, streaming, async, and async streaming agent responses.

**Result:** The first three sections returned complete responses (22.2s, 17.1s, 31.2s). The fourth section, run as the second `asyncio.run()` in the same process, failed with `Event loop is closed` from the reused async client. Run on its own in a fresh process, the same async streaming call completed (28.2s), and `Agent(model="topxai:kimi-k3")` resolved to `Topxai` and answered.

---

### tool_use.py

**Status:** PASS (sync, sync streaming, async); see note for async streaming

**Description:** Agent with `WebSearchTools()` covering sync, streaming, async, and async streaming tool calls.

**Result:** The first three sections made tool calls (`search_news` three times, `web_search` once each) and answered (47.9s, 18.2s, 25.5s). The fourth section hit the same `Event loop is closed` error as `basic.py` when run after another `asyncio.run()`.

---

### Unit tests

`libs/agno/tests/unit/models/topxai/test_topxai.py`: 7 passed, without network access.

## Catalogue refresh on 2026-10-25

Both cookbook programs now share one event loop for the two async calls, addressing the historical reused-client failure above. A regression test executes both examples with an offline Agent double that requires the same event loop.

The default and cookbook examples now use `kimi-k3.1-pro`, as listed by the live public `/api/pricing` catalogue. The older run above remains a historical `kimi-k3` result; it is not a live test of the new model. The current examples have not been rerun against a paid API in this refresh.
