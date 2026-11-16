import uuid

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from .managers import UserManager
from .phone_numbers import normalize_phone_number


class User(AbstractUser):
    class AccountType(models.TextChoices):
        ADMINISTRATOR = "administrator", "Administrator"
        VENDOR = "vendor", "Vendor"

    username = models.CharField(
        "username",
        max_length=150,
        blank=True,
        default="",
        validators=[UnicodeUsernameValidator()],
        help_text="Required for administrators. Vendors can leave this blank.",
    )
    account_type = models.CharField(
        max_length=13, choices=AccountType.choices, default=AccountType.VENDOR
    )
    phone_number = models.CharField(max_length=16, blank=True, null=True)
    business_name = models.CharField(max_length=255, blank=True, null=True)

    objects = UserManager()

    class Meta(AbstractUser.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["username"],
                condition=~Q(username=""),
                name="user_nonempty_username_unique",
            ),
            models.UniqueConstraint(
                fields=["phone_number"],
                condition=Q(account_type="vendor"),
                name="vendor_phone_unique",
            ),
            models.CheckConstraint(
                condition=Q(account_type__in=["administrator", "vendor"]),
                name="user_valid_account_type",
            ),
            models.CheckConstraint(
                condition=~Q(account_type="administrator")
                | ~Q(username__regex=r"^\s*$"),
                name="administrator_username_required",
            ),
            models.CheckConstraint(
                condition=~Q(account_type="vendor")
                | (
                    Q(phone_number__isnull=False, business_name__isnull=False)
                    & ~Q(business_name__regex=r"^\s*$")
                ),
                name="vendor_phone_and_business_required",
            ),
            models.CheckConstraint(
                condition=~Q(account_type="vendor") | Q(is_staff=False, is_superuser=False),
                name="vendor_no_admin_privileges",
            ),
            models.CheckConstraint(
                condition=Q(phone_number__isnull=True)
                | Q(phone_number__regex=r"^\+234[1-9][0-9]{9}$"),
                name="user_phone_canonical_format",
            ),
        ]

    def clean_fields(self, exclude=None):
        self.username = self.normalize_username(self.username or "").strip()
        self.business_name = (self.business_name or "").strip() or None
        if self.phone_number:
            try:
                self.phone_number = normalize_phone_number(self.phone_number)
            except ValidationError as error:
                raise ValidationError({"phone_number": error}) from error
        else:
            self.phone_number = None
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        errors = {}
        if self.account_type == self.AccountType.ADMINISTRATOR and not self.username:
            errors["username"] = "Administrators must have a username."
        if self.account_type == self.AccountType.VENDOR:
            if not self.phone_number:
                errors["phone_number"] = "Vendors must have a phone number."
            if not self.business_name:
                errors["business_name"] = "Vendors must have a business name."
            if self.is_staff:
                errors["is_staff"] = "Vendors cannot have staff privileges."
            if self.is_superuser:
                errors["is_superuser"] = "Vendors cannot have superuser privileges."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        if self.account_type == self.AccountType.ADMINISTRATOR:
            return self.username
        return f"{self.business_name} ({self.phone_number})"


class PhoneVerification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone_number = models.CharField(max_length=16, db_index=True)
    token_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    invalidated_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["phone_number"],
                condition=Q(consumed_at__isnull=True, invalidated_at__isnull=True),
                name="one_outstanding_phone_verification",
            ),
            models.CheckConstraint(
                condition=Q(phone_number__regex=r"^\+234[1-9][0-9]{9}$"),
                name="verification_phone_canonical_format",
            ),
        ]
