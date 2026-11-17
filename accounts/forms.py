from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import (
    AdminPasswordChangeForm,
    AdminUserCreationForm,
    UserChangeForm,
)
from django.core.exceptions import ValidationError

from .models import User
from .phone_numbers import local_phone_number, normalize_mobile_number, normalize_phone_number
from .validators import validate_vendor_credential


class PhoneNumberField(forms.CharField):
    def __init__(self, mobile_only=False, **kwargs):
        self.mobile_only = mobile_only
        kwargs.setdefault("max_length", 64)
        kwargs.setdefault("label", "Phone number")
        kwargs.setdefault("help_text", "Use a Nigerian number, such as 08050675448. International +234 format is also accepted.")
        kwargs.setdefault("widget", forms.TextInput(attrs={"type": "tel", "autocomplete": "tel"}))
        super().__init__(**kwargs)

    def clean(self, value):
        value = super().clean(value)
        normalizer = normalize_mobile_number if self.mobile_only else normalize_phone_number
        return normalizer(value) if value else None

    def prepare_value(self, value):
        return local_phone_number(value)


class VendorRegistrationForm(forms.Form):
    phone_number = PhoneNumberField(mobile_only=True)
    business_name = forms.CharField(
        label="Pharmacy or chemist name",
        max_length=255,
        widget=forms.TextInput(attrs={"autocomplete": "organization"}),
    )


class OTPVerificationForm(forms.Form):
    code = forms.RegexField(
        regex=r"^[0-9]{6}$",
        label="Verification code",
        max_length=6,
        min_length=6,
        widget=forms.PasswordInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code"}),
        error_messages={"invalid": "Enter the six-digit verification code."},
    )


class VendorPasswordForm(forms.Form):
    password1 = forms.CharField(
        label="Password or PIN",
        strip=False,
        max_length=128,
        help_text="Use a six-digit PIN that is hard to guess, or a password of at least eight characters.",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirm password or PIN",
        strip=False,
        max_length=128,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password1(self):
        password = self.cleaned_data["password1"]
        validate_vendor_credential(password, user=self.user)
        return password

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("password1") and cleaned_data.get("password2"):
            if cleaned_data["password1"] != cleaned_data["password2"]:
                self.add_error("password2", "The passwords or PINs do not match.")
        return cleaned_data


class VendorLoginForm(forms.Form):
    phone_number = PhoneNumberField(
        widget=forms.TextInput(attrs={"type": "tel", "autocomplete": "username", "autofocus": True}),
    )
    password = forms.CharField(
        label="Password or PIN",
        strip=False,
        max_length=128,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("phone_number") and cleaned_data.get("password"):
            self.user_cache = authenticate(
                self.request,
                phone_number=cleaned_data["phone_number"],
                password=cleaned_data["password"],
            )
            if (
                self.user_cache is None
                or self.user_cache.account_type != User.AccountType.VENDOR
                or not self.user_cache.is_active
                or self.user_cache.is_staff
                or self.user_cache.is_superuser
            ):
                self.user_cache = None
                raise ValidationError("Unable to log in. Check your details and try again.")
        return cleaned_data

    def get_user(self):
        return self.user_cache


class VendorCredentialValidationMixin:
    def validate_password_for_user(self, user, password_field_name="password2"):
        if user.account_type != User.AccountType.VENDOR:
            return super().validate_password_for_user(user, password_field_name=password_field_name)
        password = self.cleaned_data.get(password_field_name)
        if password and self.cleaned_data.get("set_usable_password", True):
            try:
                validate_vendor_credential(password, user=user)
            except ValidationError as error:
                self.add_error(password_field_name, error)


class AccountCreationForm(VendorCredentialValidationMixin, AdminUserCreationForm):
    phone_number = PhoneNumberField(required=False)

    class Meta(AdminUserCreationForm.Meta):
        model = User
        fields = ("username", "account_type", "phone_number", "business_name")


class AccountChangeForm(UserChangeForm):
    phone_number = PhoneNumberField(required=False)

    class Meta(UserChangeForm.Meta):
        model = User


class AccountPasswordChangeForm(VendorCredentialValidationMixin, AdminPasswordChangeForm):
    pass
