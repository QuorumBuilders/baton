"""Backward-compatible OTP delivery imports.

New code uses the provider-independent communication adapters directly.
"""

from communications.adapters import (
    ConsoleSMSAdapter,
    DeliveryUnavailable,
)
from communications.content import otp_sms_message
from django.conf import settings
from django.utils.module_loading import import_string


class ConsoleOTPBackend:
    """Compatibility wrapper for the former OTP-only console backend."""

    def __init__(self):
        self.adapter = ConsoleSMSAdapter()

    def send(self, phone_number, code):
        return self.adapter.send(
            otp_sms_message(
                recipient=phone_number,
                code=code,
                purpose="vendor",
                reference_id="legacy-otp",
            )
        )


def get_delivery_backend():
    if not settings.OTP_DELIVERY_BACKEND:
        raise DeliveryUnavailable("Phone verification delivery is not configured.")
    backend = import_string(settings.OTP_DELIVERY_BACKEND)()
    if isinstance(backend, ConsoleSMSAdapter):
        return ConsoleOTPBackend()
    return backend
