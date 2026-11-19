from abc import ABC, abstractmethod

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from django.utils.module_loading import import_string

from .payloads import DeliveryOutcome, DeliveryResult, SMSMessage, VoiceRequest


class DeliveryUnavailable(Exception):
    pass


class SMSAdapter(ABC):
    @abstractmethod
    def send(self, message: SMSMessage) -> DeliveryResult:
        raise NotImplementedError


class VoiceAdapter(ABC):
    @abstractmethod
    def invoke(self, request: VoiceRequest) -> DeliveryResult:
        raise NotImplementedError


class DevelopmentAdapterGuard:
    error_message = "Development communication adapters require DEBUG=True."

    def __init__(self):
        self._check_debug()

    def _check_debug(self):
        if not settings.DEBUG:
            raise ImproperlyConfigured(self.error_message)


class ConsoleSMSAdapter(DevelopmentAdapterGuard, SMSAdapter):
    """Development transport that prints every complete SMS request."""

    error_message = "Console SMS delivery requires DEBUG=True."

    def send(self, message):
        self._check_debug()
        timestamp = timezone.now().isoformat()
        print(
            "\n".join(
                (
                    "[Baton development SMS - SIMULATED]",
                    f"timestamp={timestamp}",
                    f"reference_id={message.reference_id}",
                    f"category={message.category}",
                    f"recipient={message.recipient}",
                    f"body={message.body}",
                )
            ),
            flush=True,
        )
        return DeliveryResult(
            outcome=DeliveryOutcome.SIMULATED,
            adapter=f"{type(self).__module__}.{type(self).__name__}",
            delivery_mode="development_console",
            provider_reference=message.reference_id,
        )


class MockVoiceAdapter(DevelopmentAdapterGuard, VoiceAdapter):
    """Development transport that records intent without placing a call."""

    error_message = "Mock voice delivery requires DEBUG=True."

    def invoke(self, request):
        self._check_debug()
        timestamp = timezone.now().isoformat()
        print(
            "\n".join(
                (
                    "[Baton voice invocation - MOCK / NOT A REAL CALL]",
                    f"timestamp={timestamp}",
                    f"reference_id={request.reference_id}",
                    f"recipient={request.recipient}",
                    f"category={request.category}",
                    f"language={request.language}",
                    f"recording={request.recording_reference}",
                )
            ),
            flush=True,
        )
        return DeliveryResult(
            outcome=DeliveryOutcome.SIMULATED,
            adapter=f"{type(self).__module__}.{type(self).__name__}",
            delivery_mode="development_mock",
            provider_reference=request.reference_id,
        )


def _configured_adapter(setting_name, interface, unavailable_message):
    dotted_path = getattr(settings, setting_name, "")
    if not dotted_path:
        raise DeliveryUnavailable(unavailable_message)
    adapter = import_string(dotted_path)()
    if not isinstance(adapter, interface):
        raise ImproperlyConfigured(
            f"{setting_name} must identify a {interface.__name__} implementation."
        )
    return adapter


def get_sms_adapter():
    return _configured_adapter(
        "SMS_DELIVERY_BACKEND", SMSAdapter, "SMS delivery is not configured."
    )


def get_voice_adapter():
    return _configured_adapter(
        "VOICE_DELIVERY_BACKEND", VoiceAdapter, "Voice delivery is not configured."
    )
