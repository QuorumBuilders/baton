from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import SESSION_KEY
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import PhoneVerification, User
from accounts.views import REGISTRATION_MESSAGE, REGISTRATION_SESSION_KEY


class RegistrationFlowTests(TestCase):
    code = "583029"

    def setUp(self):
        self.delivery = Mock()
        for mock in (
            patch("accounts.services.get_delivery_backend", return_value=self.delivery),
            patch("accounts.services.secrets.randbelow", return_value=int(self.code)),
        ):
            mock.start()
            self.addCleanup(mock.stop)

    def start_registration(self, **extra):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("accounts:register"), {
                "phone_number": "08012345678", "business_name": "Community Pharmacy", **extra,
            })
        self.assertRedirects(response, reverse("accounts:verify"))
        return PhoneVerification.objects.get(pk=self.client.session[REGISTRATION_SESSION_KEY]["verification_id"])

    def verify(self):
        response = self.client.post(reverse("accounts:verify"), {"code": self.code})
        self.assertRedirects(response, reverse("accounts:create_password"))

    def test_complete_registration_activates_vendor_and_starts_session(self):
        verification = self.start_registration()
        self.verify()
        previous_session_key = self.client.session.session_key
        response = self.client.post(reverse("accounts:create_password"), {
            "password1": "482953", "password2": "482953",
        })
        self.assertRedirects(response, reverse("accounts:dashboard"))
        user = User.objects.get(phone_number="+2348012345678")
        self.assertEqual(user.account_type, User.AccountType.VENDOR)
        self.assertEqual(user.username, "")
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password("482953"))
        self.assertEqual(self.client.session[SESSION_KEY], str(user.pk))
        self.assertNotEqual(previous_session_key, self.client.session.session_key)
        self.assertNotIn(REGISTRATION_SESSION_KEY, self.client.session)
        verification.refresh_from_db()
        self.assertIsNotNone(verification.completed_at)

    def test_registration_cannot_grant_administrator_privileges_or_change_verified_identity(self):
        self.start_registration(account_type="administrator", username="attacker", is_staff=True, is_superuser=True)
        self.verify()
        response = self.client.post(reverse("accounts:create_password"), {
            "password1": "482953", "password2": "482953", "account_type": "administrator",
            "username": "attacker", "is_staff": True, "is_superuser": True,
            "phone_number": "08012345679", "business_name": "Changed Name",
        })
        self.assertRedirects(response, reverse("accounts:dashboard"))
        user = User.objects.get()
        self.assertEqual(user.phone_number, "+2348012345678")
        self.assertEqual(user.business_name, "Community Pharmacy")
        self.assertEqual(user.username, "")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_password_creation_cannot_skip_phone_verification(self):
        self.start_registration()
        response = self.client.post(reverse("accounts:create_password"), {
            "password1": "482953", "password2": "482953",
        })
        self.assertRedirects(response, reverse("accounts:verify"))
        self.assertFalse(User.objects.exists())

    def test_forged_session_verification_flag_is_not_accepted(self):
        self.start_registration()
        session = self.client.session
        pending = session[REGISTRATION_SESSION_KEY]
        pending["verified"] = True
        session[REGISTRATION_SESSION_KEY] = pending
        session.save()
        response = self.client.post(reverse("accounts:create_password"), {
            "password1": "482953", "password2": "482953",
        })
        self.assertRedirects(response, reverse("accounts:register"))
        self.assertFalse(User.objects.exists())

    def test_otp_codes_and_hashes_are_never_rendered_in_responses(self):
        verification = self.start_registration()
        response = self.client.get(reverse("accounts:verify"))
        self.assertNotContains(response, self.code)
        self.assertNotContains(response, verification.token_hash)
        PhoneVerification.objects.filter(pk=verification.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        response = self.client.post(reverse("accounts:verify"), {"code": self.code})
        self.assertContains(response, "The code could not be verified.")
        self.assertNotContains(response, self.code)
        self.assertNotContains(response, verification.token_hash)

    def test_registration_duplicate_phone_response_does_not_reveal_existing_account(self):
        User.objects.create_user(phone_number="08012345678", business_name="Other Pharmacy", password="482953")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("accounts:register"), {
                "phone_number": "+2348012345678", "business_name": "Community Pharmacy",
            }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, REGISTRATION_MESSAGE)
        self.assertNotContains(response, "already registered")
        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(PhoneVerification.objects.exists())
        self.delivery.send.assert_not_called()

    def test_invalid_phone_and_blank_business_are_rejected_server_side(self):
        response = self.client.post(reverse("accounts:register"), {
            "phone_number": "+12025550123", "business_name": "   ",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("phone_number", response.context["form"].errors)
        self.assertIn("business_name", response.context["form"].errors)
        self.assertFalse(PhoneVerification.objects.exists())

    def test_empty_registration_post_shows_required_field_errors(self):
        response = self.client.post(reverse("accounts:register"), {})
        self.assertIn("phone_number", response.context["form"].errors)
        self.assertIn("business_name", response.context["form"].errors)

    def test_failed_otp_attempt_is_recorded(self):
        verification = self.start_registration()
        response = self.client.post(reverse("accounts:verify"), {"code": "000000"})
        self.assertContains(response, "The code could not be verified.")
        verification.refresh_from_db()
        self.assertEqual(verification.attempts, 1)
        self.assertIsNone(verification.consumed_at)

    def test_resend_enforces_cooldown_and_replaces_old_verification_after_wait(self):
        verification = self.start_registration()
        response = self.client.post(reverse("accounts:resend"))
        self.assertRedirects(response, reverse("accounts:verify"))
        self.delivery.send.assert_called_once()
        PhoneVerification.objects.filter(pk=verification.pk).update(created_at=timezone.now() - timedelta(seconds=61))
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("accounts:resend"))
        self.assertRedirects(response, reverse("accounts:verify"))
        self.assertNotEqual(self.client.session[REGISTRATION_SESSION_KEY]["verification_id"], str(verification.pk))
        verification.refresh_from_db()
        self.assertIsNotNone(verification.invalidated_at)
        self.assertEqual(self.delivery.send.call_count, 2)

    def test_expired_registration_grant_cannot_create_account(self):
        verification = self.start_registration()
        self.verify()
        PhoneVerification.objects.filter(pk=verification.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        response = self.client.post(reverse("accounts:create_password"), {
            "password1": "482953", "password2": "482953",
        })
        self.assertRedirects(response, reverse("accounts:register"))
        self.assertFalse(User.objects.exists())

    def test_weak_credentials_and_mismatches_do_not_create_account(self):
        self.start_registration()
        self.verify()
        for first, second in (("123456", "123456"), ("1234", "1234"), ("password", "password"), ("482953", "482954")):
            response = self.client.post(reverse("accounts:create_password"), {
                "password1": first, "password2": second,
            })
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
            self.assertFalse(User.objects.exists())

    def test_vendor_can_register_with_a_password_instead_of_pin(self):
        self.start_registration()
        self.verify()
        response = self.client.post(reverse("accounts:create_password"), {
            "password1": "Pine!Stone7quiet", "password2": "Pine!Stone7quiet",
        })
        self.assertRedirects(response, reverse("accounts:dashboard"))
        self.assertTrue(User.objects.get().check_password("Pine!Stone7quiet"))

    def test_sensitive_posts_require_csrf_and_resend_get_is_not_allowed(self):
        client = Client(enforce_csrf_checks=True)
        for route in ("register", "verify", "resend", "create_password", "login"):
            with self.subTest(route=route):
                self.assertEqual(client.post(reverse(f"accounts:{route}")).status_code, 403)
        self.assertEqual(self.client.get(reverse("accounts:resend")).status_code, 405)


class ProductionRegistrationTests(TestCase):
    @override_settings(DEBUG=False, OTP_DELIVERY_BACKEND="")
    def test_production_registration_cannot_use_development_delivery(self):
        response = self.client.post(reverse("accounts:register"), {
            "phone_number": "08012345678", "business_name": "Community Pharmacy",
        })
        self.assertContains(response, "Phone verification is unavailable.")
        self.assertFalse(PhoneVerification.objects.exists())

    @override_settings(DEBUG=False, OTP_DELIVERY_BACKEND="accounts.delivery.ConsoleOTPBackend")
    def test_explicit_console_configuration_is_still_blocked_in_production(self):
        response = self.client.post(reverse("accounts:register"), {
            "phone_number": "08012345678", "business_name": "Community Pharmacy",
        })
        self.assertContains(response, "Phone verification is unavailable.")
        self.assertFalse(PhoneVerification.objects.exists())
