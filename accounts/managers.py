from django.contrib.auth.models import UserManager as DjangoUserManager


class UserManager(DjangoUserManager):
    def _create_user_object(self, username, email, password, **extra_fields):
        if extra_fields.get("is_superuser"):
            extra_fields.setdefault("account_type", self.model.AccountType.ADMINISTRATOR)
        user = self.model(
            username=self.model.normalize_username(username or ""),
            email=self.normalize_email(email),
            **extra_fields,
        )
        user.set_password(password)
        return user

    def create_user(self, username=None, email=None, password=None, **extra_fields):
        return super().create_user(username, email, password, **extra_fields)

    async def acreate_user(self, username=None, email=None, password=None, **extra_fields):
        return await super().acreate_user(username, email, password, **extra_fields)
