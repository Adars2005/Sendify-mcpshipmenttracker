# Sendify Shipment Tracker MCP

A Python MCP server for the Sendify Code Challenge 2026. It exposes a tool named `track_db_schenker_shipment` that accepts a DB Schenker tracking reference and returns a structured result based on the public tracking page.

## Challenge compliance and current status

The challenge asks for an MCP tool that accepts a reference and returns sender/receiver information, package details, and shipment tracking history. It names the public DB Schenker tracking page as the data source and lists ten sample references. The named page currently redirects to DSV's public tracker.

| Requirement | Status | Evidence / limitation |
|---|---|---|
| MCP server and registered tracking tool | PASS | `server.py` registers `track_db_schenker_shipment` on an stdio MCP server. |
| Reference input and validation | PASS | `tracker.py` trims and validates references before source access; invalid input has a distinct status. |
| Retrieve actual carrier shipment data | PARTIAL | `tracker.py` observes JSON responses during ordinary public-page navigation. An earlier lookup returned a public record, but the latest Inspector lookup was blocked. Live access is not reliable. |
| Sender and receiver names and addresses | PARTIAL | Public locality is mapped when available. Names and street addresses were not exposed in the observed record and remain `null`. |
| Package count, weight, dimensions, identifiers | PARTIAL | Shipment-level pieces and totals and package identifiers are mapped where present. Package-specific weights/dimensions are not mapped because the observed public data did not expose a verified shape for them. |
| Available shipment tracking history | PARTIAL | Shipment events are normalized with timestamps, status, description, and location when the source provides them. Live event completeness cannot be verified while the source blocks access. |
| Per-package tracking events (bonus) | PARTIAL | Normalization supports package events when their fields match the observed event shape. The latest public result did not provide accessible package events. |
| Error handling and input safety | PASS | Invalid references, no results, source blocks, timeouts, malformed response shapes, and unexpected failures have distinct outcomes. |
| Automated tests | PASS | Offline tests cover MCP discovery/calls, validation, parsing, optional fields, events, and source errors. Mocked tests do not prove live integration. |
| Setup and usage documentation | PASS | Setup, run, Inspector, stdio client configuration, tests, limitations, and troubleshooting are documented below. |

### Live source observations

An earlier sequential check on 21 October 2026 returned a record for `3476238161`; the other nine challenge examples returned no match. A subsequent MCP Inspector lookup of `3476238161` returned `blocked` and no shipment data. Public results may change or be restricted. A `blocked` result is not evidence that the shipment does not exist. The implementation does not bypass access or verification controls.

## Architecture

- `server.py`: MCP server and tool registration.
- `tracker.py`: reference validation, normal public-page navigation, response observation, classification, and normalization.
- `models.py`: typed Pydantic result, package, party, and tracking-event models.
- `inspect_tracking_site.py`: optional diagnostic that prints response paths and JSON shapes, not payload values.
- `tests/`: deterministic offline tests using synthetic fixtures and mocks.

Shipment responses are held in memory for the current lookup and are not persisted. Logs avoid shipment references and upstream response details. There are no credentials or environment variables required by this implementation; `.env.example` documents that no secrets are needed.

## Requirements

- Python 3.11 or newer (the project was tested with Python 3.12).
- Chromium installed for Playwright live lookups.
- Windows PowerShell commands are shown below; use equivalent commands on other platforms.

## Install

From the repository root in PowerShell:

```powershell
py -3.12 -m venv .venv-project
.\.venv-project\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m playwright install chromium
```

If `py -3.12` is unavailable, install Python 3.11+ and substitute its launcher. The `dev` extra installs the MCP SDK, Playwright, Pydantic, pytest, and uv. No `.env` file is needed.

## Run with MCP Inspector

```powershell
.\.venv-project\Scripts\Activate.ps1
mcp dev server.py
```

In Inspector, connect to the server, open **Tools**, select `track_db_schenker_shipment`, enter a reference in `reference_number`, and execute. The tool returns one of these statuses: `ok`, `invalid_reference`, `not_found`, `blocked`, or `source_error`.

Keep the terminal open while using Inspector. Closing it stops the server. A live lookup can be blocked by the carrier; do not attempt to bypass a challenge, CAPTCHA, or other access control.

## Connect from an MCP client

The server uses stdio. Add an entry like this to the MCP client's server configuration, replacing both example paths with the absolute paths on your machine:

```json
{
  "mcpServers": {
    "sendify-shipment-tracker": {
      "command": "C:\\path\\to\\Sendify\\.venv-project\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\Sendify\\server.py"]
    }
  }
}
```

For this Windows checkout, the paths are:

```text
C:\Users\LENOVO\Downloads\Sendify\.venv-project\Scripts\python.exe
C:\Users\LENOVO\Downloads\Sendify\server.py
```

The client must support stdio MCP servers. Restart or refresh the client after changing its configuration, then call `track_db_schenker_shipment` with a string argument named `reference_number`.

## Result shape

The tool returns a Pydantic-validated structured object with the following fields:

```json
{
  "reference_number": "<requested reference>",
  "status": "blocked",
  "message": "The public tracking source did not allow this lookup to complete.",
  "shipment_status": null,
  "sender": {"name": null, "address": null},
  "receiver": {"name": null, "address": null},
  "piece_count": null,
  "total_weight": null,
  "weight_unit": null,
  "total_volume": null,
  "volume_unit": null,
  "loading_meters": null,
  "loading_meters_unit": null,
  "packages": [],
  "tracking_history": [],
  "warnings": ["Do not bypass access or verification controls."],
  "source_url": "<public tracking URL>"
}
```

This example represents the latest blocked lookup shape, not a successful shipment. On success, fields are populated only when the public source exposes values that the implementation can map with confidence. Missing fields stay `null` or empty and are explained in `warnings`; the implementation does not fabricate shipment details.

## Tests and checks

Activate the project environment, then run:

```powershell
python -m pytest
python -m compileall -q server.py tracker.py models.py inspect_tracking_site.py
```

The tests use synthetic payloads and mocks and do not make live requests. For an optional live diagnostic (which may be blocked), run:

```powershell
python inspect_tracking_site.py 3476238161
```

The diagnostic prints page host/path, response status, content type, and JSON key shapes only. It does not print shipment values or save response bodies.

## Troubleshooting

- **`uv` is not recognized:** activate `.venv-project` in the same PowerShell session before running `mcp dev server.py`.
- **Playwright browser missing:** run `python -m playwright install chromium` inside the activated environment.
- **Inspector reports `blocked`:** the public source denied or gated this automated lookup. The tool correctly returns no shipment data; try the public page manually or request an approved test reference from the challenge contact. Do not bypass access controls.
- **`not_found`:** the public tracker reported no matching result; challenge examples may be old or expired.
- **`source_error`:** the page timed out or returned a response the implementation could not safely map. Recheck later and inspect the public page manually.
- **MCP client cannot start the server:** confirm the configured Python and `server.py` paths are absolute and exist, then restart the client.

## Limitations and next steps

- The challenge sample references can expire, and public automated access may be blocked. The latest live result in this development session was `blocked`.
- The observed public record did not expose sender/receiver names, street addresses, package-level measurements, or per-package tracking events. Those fields remain unavailable until an approved public data source exposes them.
- The tracker maps the public response observed during normal page navigation. If the carrier changes its page or response structure, unknown structures return `source_error` rather than a fabricated success.
- If additional live test data is needed, ask the challenge contact for a current approved reference or fixture.

## References

- [Official challenge](https://github.com/holtid/Sendify-Code-Challenge-2026)
- [MCP documentation](https://modelcontextprotocol.io/)
- [Official MCP Python SDK](https://py.sdk.modelcontextprotocol.io/)
- [DB Schenker public tracking page](https://www.dbschenker.com/app/tracking-public/)

## Submission

The challenge asks for a public GitHub repository, setup instructions in its README, and the repository link emailed to `holger@sendify.se`. Be ready to explain the public-page extraction approach, the limits of the fields returned, and the difference between offline mocked tests and a successful live lookup.
