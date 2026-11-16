import re

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


def validate_vendor_credential(value, user=None):
    if re.fullmatch(r"[0-9]{6}", value):
        if len(set(value)) == 1 or value in {"123456", "654321"}:
            raise ValidationError("Choose a PIN that is harder to guess.", code="weak_pin")
        return
    if value.isdecimal():
        raise ValidationError("A PIN must contain exactly six digits.", code="invalid_pin")
    validate_password(value, user=user)
