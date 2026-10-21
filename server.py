from __future__ import annotations

import logging

from mcp.server import MCPServer

from models import ShipmentResult
from tracker import lookup_shipment

logging.basicConfig(level=logging.INFO)
mcp = MCPServer("Sendify Shipment Tracker")


@mcp.tool()
def track_db_schenker_shipment(reference_number: str) -> ShipmentResult:
    """Retrieve public shipment details and tracking history for a DB Schenker reference.

    Returns normalized sender, receiver, package, and event data when the
    current public carrier page exposes a verified, mapped shipment record.
    """
    return lookup_shipment(reference_number)


if __name__ == "__main__":
    mcp.run()
