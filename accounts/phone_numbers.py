"""Validation and canonical storage for Nigerian mobile and fixed-line numbers."""

import re

import phonenumbers
from django.core.exceptions import ValidationError


def normalize_phone_number(value):
    message = "Enter a valid Nigerian phone number, such as 08012345678."
    if not isinstance(value, str) or len(value) > 64:
        raise ValidationError(message, code="invalid_phone_number")
    value = value.strip()
    if not re.fullmatch(r"\+?[0-9 ()-]+", value):
        raise ValidationError(message, code="invalid_phone_number")
    compact = re.sub(r"[ ()-]", "", value)
    if compact.startswith("00234"):
        compact = "+" + compact[2:]
    elif compact.startswith("234"):
        compact = "+" + compact
    elif not compact.startswith(("0", "+234")):
        raise ValidationError(message, code="invalid_phone_number")
    try:
        number = phonenumbers.parse(compact, "NG")
    except phonenumbers.NumberParseException as error:
        raise ValidationError(message, code="invalid_phone_number") from error
    supported_types = {
        phonenumbers.PhoneNumberType.MOBILE,
        phonenumbers.PhoneNumberType.FIXED_LINE,
        phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE,
    }
    if (
        not phonenumbers.is_valid_number_for_region(number, "NG")
        or phonenumbers.number_type(number) not in supported_types
        or number.extension
    ):
        raise ValidationError(message, code="invalid_phone_number")
    canonical = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    if not re.fullmatch(r"\+234[1-9][0-9]{9}", canonical):
        raise ValidationError(message, code="invalid_phone_number")
    return canonical
