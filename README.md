# Sendify Shipment Tracker MCP

A Python MCP server implementing the [Sendify Code Challenge 2026](https://github.com/holtid/Sendify-Code-Challenge-2026). It exposes `track_db_schenker_shipment(reference_number)` and returns structured public shipment information.

## Implementation status

The MCP server, data models, source extraction, normalization, and error handling are implemented. The challenge's DB Schenker tracking page redirects to the official DSV public tracker. An earlier public lookup returned a shipment record for one challenge reference, but a later MCP Inspector lookup of that same reference was blocked by the public source. Live access is therefore not currently reliable. The implementation reads shipment JSON returned during the normal page workflow; it does not call an undocumented endpoint directly or bypass access controls.

The source exposes sender/receiver place-level localities, but the tested record did not include party names, street addresses, per-package weight/dimensions, or package-specific events. Those fields remain null/empty with explanatory warnings. Shipment-level piece count, total weight/volume, loading meters, package IDs, and shipment events are returned when present.

The ten challenge references were checked sequentially against the public tracker. In an earlier check, one reference returned a record and the other nine reported no matching shipment. In the latest Inspector check, the previously successful reference returned `blocked`, with no shipment data. These references may be historical, and source access can vary between attempts. A `not_found` response is distinct from source access, timeout, and layout errors.

## Architecture

- `server.py`: MCP Python SDK v2 `MCPServer`, one stdio tool, protocol boundary.
- `tracker.py`: public page lookup with Playwright, in-memory observation of JSON responses from normal page activity, source outcome classification, and normalization.
- `models.py`: Pydantic models for parties, packages, events, totals, and lookup status.
- `inspect_tracking_site.py`: optional diagnostic that prints response paths and JSON key shapes only; it does not print response values or write payloads.
- `tests/`: offline tests for schema, validation, extraction/normalization, error outcomes, chronology, and MCP tool discovery/call.

The code does not persist lookup responses. Do not commit raw shipment records or personal details.

## Requirements

- Python 3.11 or newer (development used Python 3.12).
- Windows PowerShell commands below; use the equivalent activation command on other platforms.
- Chromium installed by Playwright for live lookups.

## Install (Windows PowerShell)

```powershell
py -3.12 -m venv .venv-project
.\.venv-project\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m playwright install chromium
```

If `py -3.12` is unavailable, install Python 3.11+ from python.org and substitute its launcher command. Dependency ranges are declared in `pyproject.toml`.

## Run and inspect

```powershell
.\.venv-project\Scripts\Activate.ps1
mcp dev server.py
```

In MCP Inspector, confirm `track_db_schenker_shipment` is listed with a string argument named `reference_number`, then call it with a challenge reference. The server uses stdio; running `python server.py` directly waits for an MCP host and is not a standalone chat interface.

A local host configuration should launch the environment's absolute Python path with the absolute path to `server.py`. Keep machine-specific paths out of committed config.

## Tool result contract

Lookup statuses:

- `ok`: a public record was found and normalized.
- `invalid_reference`: input fails basic format validation.
- `not_found`: the public page or its normal data response explicitly reports no matching shipment.
- `blocked`: the source shows an access/verification barrier.
- `source_error`: timeout, unexpected source response, ambiguous record, or unmapped layout.

`shipment_status` preserves the source's latest event code. Human-readable event labels and descriptions are carried in tracking history when provided by the source. Missing values remain null/empty; the server does not infer names, street addresses, package dimensions, or per-package weights from shipment-level totals.

Illustrative synthetic response shape (values are examples, not a real shipment):

```json
{
  "reference_number": "EXAMPLE12345",
  "status": "ok",
  "message": "Public shipment information retrieved.",
  "shipment_status": "DELIVERED_CODE",
  "sender": {"name": null, "address": "10000, Example Origin, Sweden"},
  "receiver": {"name": null, "address": "20000, Example Destination, Denmark"},
  "piece_count": 2,
  "total_weight": 125.5,
  "weight_unit": "KGS",
  "total_volume": 1.25,
  "volume_unit": "CBM",
  "loading_meters": 0.5,
  "loading_meters_unit": "MTR",
  "packages": [
    {
      "reference_number": "PACKAGE-EXAMPLE",
      "weight": null,
      "weight_unit": null,
      "length": null,
      "width": null,
      "height": null,
      "dimension_unit": null,
      "piece_count": null,
      "tracking_history": []
    }
  ],
  "tracking_history": [
    {
      "timestamp": "2026-05-20T14:54:00Z",
      "status": "DELIVERED_CODE",
      "description": "Delivered",
      "location": "Example Destination",
      "package_reference": null
    }
  ],
  "warnings": [
    "Sender name is not exposed by the public record.",
    "Per-package dimensions are not exposed in the public record."
  ],
  "source_url": "https://www.dsv.com/mydsv/tracking-public/?refNumber=EXAMPLE12345&language_region=en-US_US"
}
```

## Tests

```powershell
python -m pytest
```

Tests are offline; they use synthetic values and mocks, not live shipment records. The ten challenge references and observed outcomes are listed below. The first lookup outcomes were observed on 21 October 2026; a subsequent Inspector lookup of `3476238161` returned `blocked` (also on 21 October 2026). Live source results may vary.

| Reference | Outcome |
|---|---|
| `3476472018` | `not_found` |
| `3476265230` | `not_found` |
| `3476265248` | `not_found` |
| `3476257542` | `not_found` |
| `3476238161` | Earlier lookup: `ok`; latest Inspector lookup: `blocked` |
| `3476236157` | `not_found` |
| `3476230325` | `not_found` |
| `3476219849` | `not_found` |
| `3476207869` | `not_found` |
| `3476186295` | `not_found` |

Historical examples may expire, and public access may be blocked, so record explicit no-result outcomes separately from source access errors. Live lookup is sequential and rate-conscious. The tracker reports a blocked state if the source presents access or verification controls; it does not bypass them.

## Limitations and next improvements

- Public records can omit party names, street addresses, dimensions, package-level weights, or package histories. The result leaves these unavailable fields null/empty and includes warnings.
- Shipment event status preserves the source code alongside a human-readable description where available.
- The carrier may change its public page or response structure. Unknown structures return `source_error` rather than silently looking like successful empty data.
- `inspect_tracking_site.py <reference>` can be used during maintenance to check response paths and schema keys without printing shipment values.
- The original challenge references may no longer be available. If additional current test data is needed, ask the challenge contact for an approved reference or fixture.

## References

- [Challenge README](https://github.com/holtid/Sendify-Code-Challenge-2026)
- [MCP documentation](https://modelcontextprotocol.io/)
- [Official MCP Python SDK](https://py.sdk.modelcontextprotocol.io/)
- [SDK installation](https://py.sdk.modelcontextprotocol.io/get-started/installation/)
- [SDK server run guide](https://py.sdk.modelcontextprotocol.io/run/)

## Submission

Once you have reviewed and published the repository publicly, email the repository link to `holger@sendify.se`, as requested by the challenge. Be ready to explain the extraction evidence, MCP boundary, missing-field policy, and source limitations in the technical interview.

