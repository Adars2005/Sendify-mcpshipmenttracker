from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


LookupStatus = Literal[
    "ok",
    "invalid_reference",
    "not_found",
    "blocked",
    "source_error",
]


class Party(BaseModel):
    """A sender or receiver as displayed by the public tracking source."""

    name: str | None = None
    address: str | None = None


class TrackingEvent(BaseModel):
    """One shipment or package event from the source timeline."""

    timestamp: str | None = None
    status: str | None = None
    description: str
    location: str | None = None
    package_reference: str | None = None


class Package(BaseModel):
    """A package or handling unit, with source-provided attributes only."""

    reference_number: str | None = None
    weight: float | None = None
    weight_unit: str | None = None
    length: float | None = None
    width: float | None = None
    height: float | None = None
    dimension_unit: str | None = None
    piece_count: int | None = None
    tracking_history: list[TrackingEvent] = Field(default_factory=list)


class ShipmentResult(BaseModel):
    """Stable structured result returned by the MCP tool."""

    model_config = ConfigDict(extra="forbid")

    reference_number: str
    status: LookupStatus
    message: str
    shipment_status: str | None = None
    sender: Party = Field(default_factory=Party)
    receiver: Party = Field(default_factory=Party)
    piece_count: int | None = None
    total_weight: float | None = None
    weight_unit: str | None = None
    total_volume: float | None = None
    volume_unit: str | None = None
    loading_meters: float | None = None
    loading_meters_unit: str | None = None
    packages: list[Package] = Field(default_factory=list)
    tracking_history: list[TrackingEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_url: str | None = None
