from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string


class DeliveryUnavailable(Exception):
    pass


class ConsoleOTPBackend:
    """Development delivery only. Replace send(phone_number, code) for production."""

    def __init__(self):
        if not settings.DEBUG:
            raise ImproperlyConfigured("Console OTP delivery requires DEBUG=True.")

    def send(self, phone_number, code):
        if not settings.DEBUG:
            raise ImproperlyConfigured("Console OTP delivery requires DEBUG=True.")
        print(f"[Baton development OTP] {phone_number}: {code}", flush=True)


def get_delivery_backend():
    if not settings.OTP_DELIVERY_BACKEND:
        raise DeliveryUnavailable("Phone verification delivery is not configured.")
    return import_string(settings.OTP_DELIVERY_BACKEND)()
