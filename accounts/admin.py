from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .forms import AccountChangeForm, AccountCreationForm, AccountPasswordChangeForm
from .models import User


@admin.register(User)
class AccountAdmin(UserAdmin):
    form = AccountChangeForm
    add_form = AccountCreationForm
    change_password_form = AccountPasswordChangeForm
    fieldsets = UserAdmin.fieldsets + (
        ("Baton account", {"fields": ("account_type", "phone_number", "business_name")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "account_type", "username", "phone_number", "business_name",
                    "usable_password", "password1", "password2",
                ),
            },
        ),
    )
    list_display = ("username", "phone_number", "business_name", "account_type", "is_active", "is_staff")
    list_filter = ("account_type", "is_active", "is_staff", "is_superuser")
    search_fields = ("username", "phone_number", "business_name")


# PhoneVerification is deliberately excluded from admin: OTP hashes stay private.
