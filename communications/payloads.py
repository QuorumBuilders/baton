from dataclasses import dataclass
from enum import StrEnum


class DeliveryOutcome(StrEnum):
    DELIVERED = "delivered"
    SIMULATED = "simulated"


@dataclass(frozen=True)
class DeliveryResult:
    outcome: DeliveryOutcome
    adapter: str
    delivery_mode: str
    provider_reference: str = ""


@dataclass(frozen=True)
class SMSMessage:
    recipient: str
    body: str
    category: str
    reference_id: str


@dataclass(frozen=True)
class VoiceRequest:
    recipient: str
    category: str
    language: str
    recording_reference: str
    reference_id: str
