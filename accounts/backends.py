from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ValidationError

from .phone_numbers import normalize_phone_number


class AccountBackend(ModelBackend):
    """Use administrator usernames or explicitly supplied vendor phone numbers."""

    def authenticate(self, request, username=None, password=None, phone_number=None, **kwargs):
        if password is None:
            return None
        User = get_user_model()
        if phone_number is not None:
            try:
                phone_number = normalize_phone_number(phone_number)
            except ValidationError:
                return None
            lookup = {"account_type": User.AccountType.VENDOR, "phone_number": phone_number}
        elif username:
            lookup = {
                "account_type": User.AccountType.ADMINISTRATOR,
                "username": User.normalize_username(username),
            }
        else:
            return None
        try:
            user = User.objects.get(**lookup)
        except User.DoesNotExist:
            # Preserve Django's mitigation for timing-based account enumeration.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    async def aauthenticate(self, request, **credentials):
        return await sync_to_async(self.authenticate)(request, **credentials)
