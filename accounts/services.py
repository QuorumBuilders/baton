"""Phone verification and registration rules, independent of HTTP requests."""

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from communications.adapters import DeliveryUnavailable, get_sms_adapter as get_delivery_backend
from communications.content import otp_sms_message

from .models import PhoneVerification, User
from .phone_numbers import normalize_phone_number
from .validators import validate_vendor_credential


class VerificationError(Exception):
    pass


class ResendCooldown(VerificationError):
    pass


class RegistrationError(Exception):
    pass


def issue_otp(phone_number, *, purpose="vendor"):
    if purpose not in {"vendor", "patient"}:
        raise ValueError("Unsupported verification purpose.")
    phone_number = normalize_phone_number(phone_number)
    delivery = get_delivery_backend()
    # Hash for every valid request, including registered numbers and cooldowns,
    # to avoid making account existence obvious through hashing-time differences.
    code = f"{secrets.randbelow(1_000_000):06d}"
    token_hash = make_password(code)
    now = timezone.now()
    with transaction.atomic():
        previous = (
            PhoneVerification.objects.select_for_update()
            .filter(phone_number=phone_number, purpose=purpose)
            .order_by("-created_at")
            .first()
        )
        if previous and now < previous.created_at + timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS):
            raise ResendCooldown("Please wait before requesting another code.")
        if purpose == "vendor" and User.objects.filter(account_type=User.AccountType.VENDOR, phone_number=phone_number).exists():
            return None
        PhoneVerification.objects.filter(
            phone_number=phone_number, purpose=purpose, completed_at__isnull=True, invalidated_at__isnull=True
        ).update(invalidated_at=now)
        verification = PhoneVerification.objects.create(
            phone_number=phone_number,
            purpose=purpose,
            token_hash=token_hash,
            expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
        )
        message = otp_sms_message(
            recipient=phone_number,
            code=code,
            purpose=purpose,
            reference_id=verification.pk,
        )
        transaction.on_commit(lambda: _send_verification_message(delivery, message, verification.pk))
    return verification


def _send_verification_message(delivery, message, verification_id):
    try:
        delivery.send(message)
    except Exception:
        PhoneVerification.objects.filter(pk=verification_id).update(invalidated_at=timezone.now())
        # Catch provider failures here so a DEBUG error page cannot expose the
        # plaintext OTP or the provider's sensitive exception payload.
        raise DeliveryUnavailable("Phone verification delivery is unavailable.") from None


def _current_verification(verification_id, phone_number, *, purpose="vendor", for_registration=False):
    try:
        phone_number = normalize_phone_number(phone_number)
        verification = PhoneVerification.objects.get(pk=verification_id, phone_number=phone_number, purpose=purpose)
    except (PhoneVerification.DoesNotExist, ValidationError, ValueError, TypeError):
        raise VerificationError("The verification is unavailable. Request a new code.") from None
    expires_at = verification.expires_at
    # Patient creation has its own window after verification; OTP validation
    # and vendor registration still use the original code expiry.
    if for_registration and purpose == "patient" and verification.consumed_at is not None:
        expires_at = verification.consumed_at + timedelta(seconds=settings.PATIENT_REGISTRATION_TTL_SECONDS)
    if (
        verification.invalidated_at is not None
        or verification.completed_at is not None
        or expires_at <= timezone.now()
    ):
        raise VerificationError("The verification is unavailable. Request a new code.")
    return verification


def verify_otp(verification_id, phone_number, code, *, purpose="vendor"):
    verification = _current_verification(verification_id, phone_number, purpose=purpose)
    if verification.consumed_at is not None or verification.attempts >= settings.OTP_MAX_ATTEMPTS:
        raise VerificationError("The code could not be verified. Request a new code.")
    outstanding = PhoneVerification.objects.filter(
        pk=verification.pk,
        phone_number=verification.phone_number,
        consumed_at__isnull=True,
        invalidated_at__isnull=True,
        completed_at__isnull=True,
        expires_at__gt=timezone.now(),
        attempts__lt=settings.OTP_MAX_ATTEMPTS,
    )
    if not isinstance(code, str) or not check_password(code, verification.token_hash):
        outstanding.update(attempts=F("attempts") + 1)
        raise VerificationError("The code could not be verified. Request a new code.")
    now = timezone.now()
    if outstanding.filter(expires_at__gt=now).update(consumed_at=now) != 1:
        raise VerificationError("The code could not be verified. Request a new code.")
    verification.consumed_at = now
    return verification


def get_verified_registration(verification_id, phone_number, *, purpose="vendor"):
    verification = _current_verification(
        verification_id, phone_number, purpose=purpose, for_registration=True
    )
    if verification.consumed_at is None:
        raise VerificationError("Verify your phone number before creating an account.")
    return verification


def complete_registration(verification_id, phone_number, business_name, password):
    verification = get_verified_registration(verification_id, phone_number)
    user = User(
        account_type=User.AccountType.VENDOR,
        username="",
        phone_number=verification.phone_number,
        business_name=business_name,
        is_active=True,
        is_staff=False,
        is_superuser=False,
    )
    validate_vendor_credential(password, user=user)
    user.set_password(password)
    try:
        with transaction.atomic():
            # A conditional update claims the grant once, including on SQLite.
            claimed = PhoneVerification.objects.filter(
                pk=verification.pk,
                phone_number=verification.phone_number,
                consumed_at__isnull=False,
                completed_at__isnull=True,
                invalidated_at__isnull=True,
                expires_at__gt=timezone.now(),
            ).update(completed_at=timezone.now())
            if claimed != 1:
                raise RegistrationError("Registration could not be completed. Start again.")
            user.save()
    except (IntegrityError, ValidationError) as error:
        raise RegistrationError("Registration could not be completed. Start again or log in.") from error
    return user
