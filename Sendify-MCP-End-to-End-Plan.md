# Sendify Shipment Tracker MCP — End-to-End Implementation Plan

**Prepared:** 21 October 2026  
**Purpose:** A beginner-friendly, execution-ready plan for completing the [Sendify Code Challenge 2026](https://github.com/holtid/Sendify-Code-Challenge-2026).

## 1. Outcome and scope

Build a small Python MCP server with one discoverable tool, `track_db_schenker_shipment(reference_number)`. Given a reference, it should use the current, publicly accessible DB Schenker/DSV tracking workflow, extract what that workflow actually exposes, normalize the result into a stable structured response, and communicate errors honestly.

The challenge requires sender and receiver name/address, package details (including weight, dimensions, and piece count where available), and the complete shipment tracking history. Package-specific histories are a bonus. The deliverable also needs reproducible environment, install, run, and test instructions in a public GitHub repository. The challenge lists ten sample references and asks applicants to email the repository link to `holger@sendify.se`.

**Not in scope:** a web/mobile UI, a chatbot, a custom LLM call, a database, remote hosting, or speculative features. Add caching only if later evidence shows it is useful, compliant with source terms, and safe for shipment data.

## 2. Important facts and assumptions to verify

- The challenge names `https://www.dbschenker.com/app/tracking-public/` as the source. The supplied guide says that this has redirected to DSV and suggests a DSV tracking URL. Confirm the current official user-facing destination during reconnaissance; document the observed date and final URL. Do not bake in an unverified API endpoint.
- The current official Python SDK docs describe `mcp` 2.x as stable, require Python 3.11+, and use `MCPServer` (`from mcp.server import MCPServer`). This differs from many older v1 tutorials using `FastMCP`. Pin the major version and follow one version's docs consistently.
- The exact current response schema, page selectors, accessible fields, and continued availability of the example references are unknown until tested. Treat all sample references as test inputs, not proof that records still exist.
- Never guess or synthesize shipment facts. Keep absent fields `null`/empty and explain the missing data. Do not defeat CAPTCHA, access controls, rate limits, or anti-bot measures.

## 3. Proposed architecture

```text
MCP host/client
    │ MCP tool call: reference_number
    ▼
server.py ── input validation, status/error mapping, MCP result
    │
    ▼
tracker.py ── public source retrieval, raw record selection, normalization
    │
    ├── normal public JSON response, if observed and usable
    └── rendered public page, if that is the only legitimate usable source
    ▼
models.py ── stable ShipmentResult, Party, Package, TrackingEvent models
```

Keep protocol handling separate from source-specific extraction. Keep captured payloads local and sanitized; tests should use synthetic/redacted fixtures, never real personal or shipment data. Use `logging` to stderr for diagnostics. Stdio is the recommended first transport because this is a local MCP server; do not add HTTP hosting without a concrete deployment need.

## 4. Proposed project layout

```text
sendify-shipment-mcp/
├── .gitignore
├── README.md
├── pyproject.toml           # dependencies and project/tool configuration
├── server.py                # MCP tool and public entry point
├── tracker.py               # fetch, extraction, normalization, typed source errors
├── models.py                # validated output models/status types
├── inspect_tracking_site.py # local-only reconnaissance helper; no committed dumps
├── tests/
│   ├── fixtures/            # synthetic or sanitized fixtures only
│   ├── test_validation.py
│   ├── test_normalization.py
│   ├── test_source_errors.py
│   └── test_mcp_tool.py
└── .github/workflows/       # optional CI after the core works
```

A `pyproject.toml` and lock file are preferable to undocumented ad hoc installs, but keep setup simple and provide PowerShell commands in the README. If using a different dependency manager, commit its reproducible lock file.

## 5. Phase-by-phase execution

### Phase 0 — Repository and environment setup

1. Create a dedicated project directory/repository; keep the current Python environment isolated with `.venv`.
2. Use Python 3.11 or newer. Add dependency declarations for the official MCP Python SDK with CLI, Playwright, Pydantic, and pytest; pin compatible ranges and lock resolved versions.
3. Install Playwright's Chromium browser only if reconnaissance confirms browser automation is needed.
4. Add `.venv/`, caches, `.env`, browser reports, logs, and any `debug_payloads/` directory to `.gitignore` before capturing data.
5. Record `python --version` and dependency versions in the development notes.

**Gate:** a clean environment can install the declared dependencies from the documented commands.

### Phase 1 — Reconnaissance before scraper implementation

1. Open the original challenge tracking URL normally, note redirects and current official destination, and check the official site terms/robots or usage guidance relevant to automated public lookups.
2. Manually submit one challenge reference using the site's normal interface. Determine whether the shipment is still available and what fields the public page displays.
3. In browser DevTools, inspect normal Fetch/XHR responses and rendered page text. Record the request shape, response content type, status, useful data paths, and visible fields. Do not treat a guessed/private endpoint as a documented contract.
4. If using Playwright, use a diagnostic-only script to capture matching responses and visible text from ordinary page activity. Save captures only locally; redact personal/company/address/phone information before turning any sample into a fixture.
5. Repeat with another reference only if needed to understand variant shapes or whether the first sample is stale.
6. Decide on one primary strategy: parse a legitimate structured response if normal page activity exposes one; otherwise extract user-visible rendered content with resilient locators. Avoid implementing both until evidence calls for a fallback.
7. Stop automated requests and classify the outcome if the site presents CAPTCHA, access denial, or another verification barrier. Do not bypass it. Document the limitation and seek an approved test/data access route if needed.

**Reconnaissance record:** date, tested references, redirects, observed status/page message, field availability, chosen extraction source, and constraints. Keep sensitive raw data out of Git.

**Gate:** evidence identifies a legitimate, repeatable extraction route and real field mapping, or documents a blocker that requires an approved alternative. Do not claim the tracker works until this gate passes.

### Phase 2 — Define the result contract

Use Pydantic models (or equivalently validated models) for a consistent response. Keep reference numbers as strings so leading zeros are preserved.

Recommended shape:

```json
{
  "reference_number": "3476472018",
  "status": "ok",
  "message": "Shipment information retrieved",
  "sender": {"name": null, "address": null},
  "receiver": {"name": null, "address": null},
  "packages": [],
  "tracking_history": [],
  "warnings": [],
  "source_url": "https://www.dsv.com/mydsv/tracking-public/"
}
```

This is a contract example, not a claim about the current data for that reference. Define:

- `Party`: `name`, `address`, with absent values as null.
- `Package`: reference, weight and unit, dimensions and unit, piece count, and optional package-level events.
- `TrackingEvent`: timestamp (retain source text or normalize to ISO-8601 with timezone when possible), status, description, location, and package reference where available.
- `ShipmentResult`: requested reference, a finite status, user-safe message, sender, receiver, packages, shipment history, warnings, and source URL.

Recommended statuses: `ok`, `invalid_reference`, `not_found`, `blocked`, and `source_error`. Define which source outcomes map to each. `not_found` means the public source explicitly says no matching result; it must not mean timeout, parser failure, or missing detail. Include a warning when requested fields are not exposed. Avoid a success-shaped result for a block or failed lookup.

**Gate:** schemas are agreed before source mappings are coded; missing/optional values validate without invented defaults.

### Phase 3 — Implement `tracker.py`

Build and verify these responsibilities independently of MCP:

1. `fetch_tracking_data(reference_number)`: perform one bounded lookup through the chosen public workflow; configure finite navigation/request timeouts and a small, explicitly bounded retry only for transient network failures.
2. `extract_raw_shipment(response_or_page)`: distinguish a real matching record, explicit no-result page, block/verification page, and unexpected/malformed content.
3. `normalize_shipment(raw)`: use only field paths/selectors recorded during reconnaissance; normalize parties, packages, units, and every available tracking event.
4. `lookup_shipment(reference_number)`: coordinate the above and return a `ShipmentResult` or raise narrowly typed internal source exceptions.

Normalization rules:

- Preserve source semantics and units; convert units only if conversion is explicit, correct, and documented.
- Keep missing values null and add concise warnings for incomplete fields.
- Include every available shipment event. Sort chronologically only when timestamps can be parsed safely; document timezone assumptions and keep original text if ambiguous.
- Deduplicate only when the source clearly duplicates the same event; avoid collapsing events that differ in status/location/time.
- Associate package timelines only when the source explicitly links events to a package.
- Treat changed or unknown payload shapes as `source_error`, with a safe log diagnostic; do not silently return empty success data.

**Gate:** fixture-driven extraction handles a representative successful record and explicit missing, blocked, timeout, malformed, and partial-data cases.

### Phase 4 — Expose the MCP tool in `server.py`

1. Create `MCPServer` using the current SDK v2 import and register exactly one required tool: `track_db_schenker_shipment`.
2. Define a string parameter `reference_number`, clear tool description, and Pydantic structured output schema if supported by the current SDK's output contract.
3. Validate trimmed input using a conservative, documented format check that accepts known challenge references. Do not overconstrain legitimate carrier reference formats without evidence. Do not convert reference to an integer.
4. Map known outcomes to the result statuses. Catch expected source exceptions specifically. Log unexpected exceptions and return a generic `source_error`; do not leak stack traces or raw source payloads to the caller.
5. Run with the default stdio transport and guard startup with `if __name__ == "__main__": mcp.run()`. Keep stdout clean during server startup/operation; use logging.

**Gate:** importing the module does not start the process; a real MCP client can discover the exact tool and schema and receive structured results.

### Phase 5 — Tests and live evaluation

Write tests as part of completion (the challenge expects evidence of correctness):

- Reference validation, whitespace trimming, leading-zero preservation, and invalid input.
- Normalization of sender/receiver, packages, units, and all event fields.
- Missing fields, missing timestamps/locations, variant or unknown optional fields, and timezone/event order policy.
- Explicit not-found, blocked, timeout, network error, malformed response, and changed schema.
- Package event linkage only where supported.
- MCP tool listing, input schema, structured output, and status mapping using an in-memory SDK client where practical.
- No test should depend on live network or store real shipment data. If a manual live smoke test is run, keep it opt-in and rate-limited.

Then run the challenge's ten reference numbers once, sequentially and at a polite pace, using the public workflow. Record a local or sanitized status matrix with status and which categories of fields were present; do not commit personal data. Distinguish historical references no longer found from software defects. Never fabricate responses to make every sample pass.

**Gate:** deterministic tests pass; MCP Inspector can connect, list the tool, validate its schema, and call it; live results are honestly classified for all ten references or the source limitation is documented.

### Phase 6 — Documentation and polish

README sections:

1. Project purpose and challenge link.
2. Architecture and data flow.
3. Prerequisites (Python 3.11+, supported OS/browser if Playwright is used).
4. Windows PowerShell setup/install commands from a clean checkout.
5. How to run under MCP Inspector (`mcp dev server.py`) and directly as stdio (explain that it waits for an MCP client and is not a terminal chatbot).
6. Tool name, argument, result schema, status meanings, and sanitized illustrative response.
7. Tests and how to run them; ten reference list and how live results were evaluated.
8. Source behavior, redirect/current URL observations, fields the source omits, privacy/rate-limit/access constraints, and known limitations.
9. MCP host configuration example with absolute local Python/server paths, clearly marked as environment-specific.
10. Troubleshooting and interview design trade-offs.

Before publishing, check README commands against the actual project and ensure the example result is not presented as a real lookup.

### Phase 7 — Submission

1. Review repository status and diff; remove raw captures, personal shipment details, credentials, local paths, and generated browser artifacts.
2. Confirm `.gitignore`, dependency lock, clean setup instructions, and public repository visibility.
3. Push the completed solution to a public GitHub repository under the applicant's account.
4. Send the repository link to `holger@sendify.se`, as the challenge requires. Include a concise note that identifies the project and, if applicable, any source access limitation.
5. Prepare to explain the extraction evidence, MCP boundary, normalization policy, errors, and trade-offs in an interview.

## 6. Acceptance checklist

- [ ] One MCP tool with the required exact name and a reference-string input.
- [ ] Structured sender and receiver values when the source exposes them.
- [ ] Package attributes and all available shipment events represented.
- [ ] Package event histories implemented only if source data supports reliable association; otherwise documented as unpopulated bonus scope.
- [ ] Missing values are null/empty with useful warnings, never fabricated.
- [ ] Invalid input, explicit no-result, blocked access, timeout, and malformed/source failure are distinguishable.
- [ ] Source extraction is based on observed normal public behavior and respects access controls.
- [ ] Unit/contract tests run without live network or real shipment records.
- [ ] Inspector discovery and a manual tool call succeed.
- [ ] All ten challenge references have honest, privacy-safe outcome notes.
- [ ] A clean install, run, and test are reproducible from README instructions.
- [ ] Public repository has no secrets or raw personal shipment dumps; repository link submitted by email.

## 7. Main risks and responses

| Risk | Response |
|---|---|
| Challenge references are historical or unavailable | Mark explicit `not_found` only when source says so; distinguish from source/access failures and document the live test result. |
| Carrier changes page/API structure | Isolate extraction, validate expected structure, maintain sanitized fixtures, and fail visibly as `source_error`. |
| CDN/CAPTCHA or anti-bot block | Stop automated attempts; return `blocked`; ask for an approved alternative rather than bypassing controls. |
| Public source omits party/package fields | Keep null, explain limitations, and ask the challenge contact for approved sample data if needed. |
| Real shipment details leak in Git/history | Keep captures local, redact fixtures, inspect staged files and repository history before publishing. |
| SDK tutorial/version mismatch | Pin `mcp>=2,<3` (or the selected exact compatible release), use current official v2 docs, and verify Inspector/client compatibility. |

## 8. Reference links

- [Sendify Code Challenge 2026](https://github.com/holtid/Sendify-Code-Challenge-2026) — task, requirements, ten sample references, technical expectations, submission route, and interview expectations.
- [MCP introduction](https://modelcontextprotocol.io/) — MCP as a standard connection between AI applications and external tools/data/workflows.
- [MCP architecture](https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture) — host/client/server concepts and protocol architecture.
- [MCP GitHub organization](https://github.com/modelcontextprotocol) — specification, official SDKs, and Inspector projects.
- [Official Python SDK installation](https://py.sdk.modelcontextprotocol.io/get-started/installation/) — current Python requirement, SDK installation, and CLI extras.
- [Official Python SDK: running a server](https://py.sdk.modelcontextprotocol.io/run/) — MCPServer setup, stdio default, Inspector workflow, and logging considerations.
- [Official Python SDK: first steps](https://py.sdk.modelcontextprotocol.io/get-started/first-steps/) — current decorators, inferred schemas, and tool discovery concepts.

---

## Completion definition

The plan is complete when every acceptance item is either satisfied with evidence or transparently marked as blocked by the public source and addressed through the challenge contact. A tool that merely appears in Inspector is not a complete shipment tracker: extraction, honest normalization, failure handling, reproducible documentation, and submission are all part of the end-to-end result.
