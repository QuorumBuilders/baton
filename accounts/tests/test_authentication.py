from asgiref.sync import async_to_sync
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import SESSION_KEY, authenticate
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import PhoneVerification, User


class AuthenticationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.administrator = User.objects.create_superuser(
            "administrator", password="Pine!Stone7quiet", phone_number="08012345670",
        )
        cls.vendor = User.objects.create_user(
            username="vendor-alias", phone_number="08012345678",
            business_name="Community Pharmacy", password="482953",
        )
        cls.inactive = User.objects.create_user(
            phone_number="08012345679", business_name="Community Pharmacy", password="482953", is_active=False,
        )
        cls.nonstaff_administrator = User.objects.create_user(
            username="nonstaff", account_type=User.AccountType.ADMINISTRATOR, password="Pine!Stone7quiet",
        )

    def test_administrator_username_authentication(self):
        self.assertEqual(authenticate(username="administrator", password="Pine!Stone7quiet"), self.administrator)

    def test_vendor_phone_authentication_normalizes_input(self):
        for number in ("08012345678", "+2348012345678", "2348012345678"):
            with self.subTest(number=number):
                self.assertEqual(authenticate(phone_number=number, password="482953"), self.vendor)

    def test_existing_fixed_line_vendor_can_still_authenticate(self):
        fixed_line_vendor = User.objects.create_user(
            phone_number="02012345678",
            business_name="Legacy Fixed Line Pharmacy",
            password="482953",
        )
        self.assertEqual(
            authenticate(phone_number="02012345678", password="482953"),
            fixed_line_vendor,
        )

    def test_vendor_cannot_authenticate_with_business_name_or_username(self):
        self.assertIsNone(authenticate(username="vendor-alias", password="482953"))
        self.assertIsNone(authenticate(phone_number="Community Pharmacy", password="482953"))

    def test_invalid_credentials_and_inactive_accounts_are_rejected(self):
        for credentials in (
            {"username": "administrator", "password": "wrong"},
            {"phone_number": "08012345678", "password": "wrong"},
            {"phone_number": "08012345679", "password": "482953"},
            {"phone_number": "+12025550123", "password": "482953"},
            {"username": "missing", "password": "wrong"},
        ):
            with self.subTest(credentials=credentials):
                self.assertIsNone(authenticate(**credentials))
        User.objects.filter(pk=self.administrator.pk).update(is_active=False)
        self.assertIsNone(authenticate(username="administrator", password="Pine!Stone7quiet"))

    def test_async_authentication_uses_the_same_role_boundaries(self):
        from django.contrib.auth import aauthenticate

        self.assertEqual(async_to_sync(aauthenticate)(phone_number="08012345678", password="482953"), self.vendor)
        self.assertIsNone(async_to_sync(aauthenticate)(username="vendor-alias", password="482953"))

    def test_login_creates_a_django_session_and_logout_flushes_it(self):
        self.assertEqual(reverse("accounts:login"), "/login/")
        response = self.client.post("/login/", {
            "phone_number": "08012345678", "password": "482953",
        })
        self.assertRedirects(response, reverse("accounts:dashboard"))
        self.assertEqual(self.client.session[SESSION_KEY], str(self.vendor.pk))
        confirmation = self.client.get(reverse("accounts:logout"))
        self.assertEqual(confirmation.status_code, 200)
        self.assertIn(SESSION_KEY, self.client.session)
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("core:landing"))
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_login_rejects_external_next_redirect(self):
        response = self.client.post(reverse("accounts:login"), {
            "phone_number": "08012345678", "password": "482953",
            "next": "https://example.org/steal-session",
        })
        self.assertRedirects(response, reverse("accounts:dashboard"))

    def test_login_errors_are_generic_for_inactive_and_unknown_accounts(self):
        for number in ("08012345679", "08012345670"):
            response = self.client.post(reverse("accounts:login"), {
                "phone_number": number, "password": "482953",
            })
            self.assertContains(response, "Unable to log in. Check your details and try again.")
            self.assertNotIn(SESSION_KEY, self.client.session)

    def test_public_login_form_has_only_vendor_credentials(self):
        response = self.client.get("/login/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/login.html")
        self.assertEqual(set(response.context["form"].fields), {"phone_number", "password"})
        self.assertContains(response, 'type="tel"')
        self.assertNotContains(response, 'name="account_type"')
        self.assertNotContains(response, "Administrator")
        self.assertNotContains(response, reverse("admin:login"))

    def test_legacy_login_address_redirects_to_vendor_login(self):
        response = self.client.get("/accounts/login/?next=/accounts/dashboard/")
        self.assertRedirects(response, "/login/?next=/accounts/dashboard/")

    def test_administrator_credentials_cannot_log_in_through_public_form(self):
        for data in (
            {"phone_number": self.administrator.phone_number},
            {"account_type": "administrator", "identifier": self.administrator.username},
        ):
            with self.subTest(data=data):
                response = self.client.post("/login/", data | {"password": "Pine!Stone7quiet"})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
                self.assertNotIn(SESSION_KEY, self.client.session)

    def test_public_login_rejects_nonvendor_even_if_backend_returns_one(self):
        with patch("accounts.forms.authenticate", return_value=self.administrator):
            response = self.client.post("/login/", {
                "phone_number": "08012345678", "password": "482953",
            })
        self.assertContains(response, "Unable to log in. Check your details and try again.")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_public_login_cannot_grant_privileges_or_redirect_vendor_into_admin(self):
        response = self.client.post("/login/", {
            "phone_number": "+2348012345678", "password": "482953",
            "account_type": "administrator", "username": self.administrator.username,
            "is_staff": "on", "is_superuser": "on", "next": reverse("admin:index"),
        })
        self.assertRedirects(response, reverse("accounts:dashboard"))
        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.account_type, User.AccountType.VENDOR)
        self.assertFalse(self.vendor.is_staff)
        self.assertFalse(self.vendor.is_superuser)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)

    def test_authenticated_administrator_returns_to_named_admin_entry_point(self):
        self.client.force_login(self.administrator)
        response = self.client.get("/login/")
        self.assertRedirects(response, reverse("admin:index"))

    def test_anonymous_vendor_dashboard_access_requires_login(self):
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('accounts:dashboard')}")

    def test_vendor_cannot_access_admin_or_grant_privileges_through_admin(self):
        self.client.force_login(self.vendor)
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)
        response = self.client.post(reverse("admin:accounts_user_add"), {
            "username": "escalation", "account_type": "administrator", "is_superuser": True,
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(username="escalation").exists())

    def test_admin_login_preserves_django_admin_permissions(self):
        response = self.client.post(reverse("admin:login"), {
            "username": "administrator", "password": "Pine!Stone7quiet", "next": reverse("admin:index"),
        })
        self.assertRedirects(response, reverse("admin:index"))
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:accounts_user_changelist")).status_code, 200)
        self.assertNotIn(PhoneVerification, admin.site._registry)

    def test_account_type_alone_does_not_grant_admin_access(self):
        self.client.force_login(self.nonstaff_administrator)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)

    def test_nonstaff_administrator_cannot_log_in_to_django_admin(self):
        response = self.client.post(reverse("admin:login"), {
            "username": "nonstaff", "password": "Pine!Stone7quiet", "next": reverse("admin:index"),
        })
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "admin/login.html")
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)

    def test_vendor_credentials_cannot_log_in_to_django_admin(self):
        response = self.client.post(reverse("admin:login"), {
            "username": self.vendor.username, "password": "482953", "next": reverse("admin:index"),
        })
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "admin/login.html")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_staff_access_still_requires_django_model_permissions(self):
        user = self.nonstaff_administrator
        user.is_staff = True
        user.save()
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)
        url = reverse("admin:accounts_user_changelist")
        self.assertEqual(self.client.get(url).status_code, 403)
        user.user_permissions.add(Permission.objects.get(
            codename="view_user", content_type__app_label="accounts",
        ))
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_staff_can_search_filter_and_activate_or_deactivate_vendor(self):
        self.client.force_login(self.administrator)
        response = self.client.get(reverse("admin:accounts_user_changelist"), {
            "q": self.vendor.phone_number, "account_type__exact": "vendor", "is_active__exact": "1",
        })
        self.assertContains(response, "Community Pharmacy")
        payload = {
            "username": self.vendor.username, "account_type": "vendor",
            "phone_number": self.vendor.phone_number, "business_name": self.vendor.business_name,
            "date_joined_0": self.vendor.date_joined.strftime("%Y-%m-%d"),
            "date_joined_1": self.vendor.date_joined.strftime("%H:%M:%S"),
        }
        url = reverse("admin:accounts_user_change", args=[self.vendor.pk])
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302)
        self.vendor.refresh_from_db()
        self.assertFalse(self.vendor.is_active)
        response = self.client.post(url, payload | {"is_active": "on"})
        self.assertEqual(response.status_code, 302)
        self.vendor.refresh_from_db()
        self.assertTrue(self.vendor.is_active)

    def test_deactivated_vendor_loses_protected_session_access(self):
        self.client.force_login(self.vendor)
        User.objects.filter(pk=self.vendor.pk).update(is_active=False)
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 302)

    def test_logout_requires_csrf_for_post(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.vendor)
        self.assertEqual(client.post(reverse("accounts:logout")).status_code, 403)
        self.assertIn(SESSION_KEY, client.session)
