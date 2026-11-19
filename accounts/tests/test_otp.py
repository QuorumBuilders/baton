from contextlib import redirect_stdout
from datetime import timedelta
from io import StringIO
import re
from unittest.mock import Mock, patch

from django.contrib.auth.hashers import check_password
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from accounts.delivery import ConsoleOTPBackend, DeliveryUnavailable, get_delivery_backend
from accounts.models import PhoneVerification, User
from accounts.services import (
    ResendCooldown, VerificationError, complete_registration, issue_otp, verify_otp,
)


class OTPTests(TestCase):
    def setUp(self):
        self.delivery = Mock()
        backend = patch("accounts.services.get_delivery_backend", return_value=self.delivery)
        backend.start()
        self.addCleanup(backend.stop)
        self.verification, self.code = self.issue()

    def issue(self, phone_number="08012345678"):
        with self.captureOnCommitCallbacks(execute=True):
            verification = issue_otp(phone_number)
        message = self.delivery.send.call_args.args[0]
        return verification, re.search(r"\b([0-9]{6})\b", message.body).group(1)

    def allow_resend(self):
        PhoneVerification.objects.filter(pk=self.verification.pk).update(
            created_at=timezone.now() - timedelta(seconds=61)
        )

    def test_only_hash_is_stored_and_delivery_uses_canonical_phone(self):
        self.assertEqual(self.verification.phone_number, "+2348012345678")
        self.assertNotEqual(self.verification.token_hash, self.code)
        self.assertTrue(check_password(self.code, self.verification.token_hash))
        self.assertEqual(len(self.code), 6)
        self.delivery.send.assert_called_once()
        message = self.delivery.send.call_args.args[0]
        self.assertEqual(message.recipient, "+2348012345678")
        self.assertEqual(message.category, "vendor_otp")
        self.assertEqual(message.reference_id, str(self.verification.pk))
        self.assertIn(self.code, message.body)
        self.assertIn("Do not share", message.body)

    def test_successful_verification_is_single_use(self):
        verify_otp(self.verification.pk, "08012345678", self.code)
        self.verification.refresh_from_db()
        self.assertIsNotNone(self.verification.consumed_at)
        with self.assertRaises(VerificationError):
            verify_otp(self.verification.pk, "+2348012345678", self.code)

    def test_expired_code_is_rejected(self):
        PhoneVerification.objects.filter(pk=self.verification.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(VerificationError):
            verify_otp(self.verification.pk, "08012345678", self.code)

    @override_settings(OTP_MAX_ATTEMPTS=3)
    def test_failed_attempts_persist_and_limit_prevents_correct_code(self):
        wrong_code = "000000" if self.code != "000000" else "111111"
        for _ in range(4):
            with self.assertRaises(VerificationError):
                verify_otp(self.verification.pk, "08012345678", wrong_code)
        self.verification.refresh_from_db()
        self.assertEqual(self.verification.attempts, 3)
        with self.assertRaises(VerificationError):
            verify_otp(self.verification.pk, "08012345678", self.code)

    def test_resend_cooldown_does_not_replace_or_deliver_code(self):
        with self.assertRaises(ResendCooldown):
            issue_otp("+2348012345678")
        self.assertEqual(PhoneVerification.objects.count(), 1)
        self.delivery.send.assert_called_once()

    def test_resend_invalidates_previous_outstanding_code(self):
        self.allow_resend()
        replacement, code = self.issue()
        self.verification.refresh_from_db()
        self.assertIsNotNone(self.verification.invalidated_at)
        with self.assertRaises(VerificationError):
            verify_otp(self.verification.pk, "08012345678", self.code)
        verify_otp(replacement.pk, "08012345678", code)

    def test_verification_is_bound_to_exact_phone(self):
        with self.assertRaises(VerificationError):
            verify_otp(self.verification.pk, "08012345679", self.code)
        self.verification.refresh_from_db()
        self.assertIsNone(self.verification.consumed_at)
        self.assertEqual(self.verification.attempts, 0)

    def test_unverified_phone_cannot_complete_registration(self):
        with self.assertRaises(VerificationError):
            complete_registration(self.verification.pk, "08012345678", "Community Pharmacy", "482953")
        self.assertFalse(User.objects.exists())

    def test_registration_grant_is_used_once_and_account_is_activated(self):
        verify_otp(self.verification.pk, "08012345678", self.code)
        user = complete_registration(
            self.verification.pk, "08012345678", "Community Pharmacy", "482953"
        )
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password("482953"))
        self.verification.refresh_from_db()
        self.assertIsNotNone(self.verification.completed_at)
        with self.assertRaises(VerificationError):
            complete_registration(self.verification.pk, "08012345678", "Community Pharmacy", "482953")
        self.assertEqual(User.objects.count(), 1)

    def test_new_code_invalidates_previously_verified_registration_grant(self):
        verify_otp(self.verification.pk, "08012345678", self.code)
        self.allow_resend()
        self.issue()
        with self.assertRaises(VerificationError):
            complete_registration(self.verification.pk, "08012345678", "Community Pharmacy", "482953")

    def test_registration_grant_expires_after_verification(self):
        verify_otp(self.verification.pk, "08012345678", self.code)
        PhoneVerification.objects.filter(pk=self.verification.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(VerificationError):
            complete_registration(self.verification.pk, "08012345678", "Community Pharmacy", "482953")

    def test_vendor_registration_deadline_stays_at_original_otp_expiry(self):
        expires_at = self.verification.expires_at
        with patch("accounts.services.timezone.now", return_value=expires_at - timedelta(seconds=1)):
            verify_otp(self.verification.pk, "08012345678", self.code)
        with patch("accounts.services.timezone.now", return_value=expires_at):
            with self.assertRaises(VerificationError):
                complete_registration(self.verification.pk, "08012345678", "Community Pharmacy", "482953")
        self.assertFalse(User.objects.exists())


class DeliveryTests(SimpleTestCase):
    @override_settings(DEBUG=True)
    def test_console_delivery_is_available_in_development(self):
        output = StringIO()
        with redirect_stdout(output):
            ConsoleOTPBackend().send("+2348012345678", "583029")
        self.assertIn("583029", output.getvalue())

    @override_settings(DEBUG=False)
    def test_console_backend_cannot_be_created_in_production(self):
        with self.assertRaises(ImproperlyConfigured):
            ConsoleOTPBackend()

    def test_console_backend_checks_debug_again_before_delivery(self):
        with override_settings(DEBUG=True):
            backend = ConsoleOTPBackend()
        with override_settings(DEBUG=False):
            with self.assertRaises(ImproperlyConfigured):
                backend.send("+2348012345678", "583029")

    @override_settings(OTP_DELIVERY_BACKEND="")
    def test_unconfigured_delivery_is_unavailable(self):
        with self.assertRaises(DeliveryUnavailable):
            get_delivery_backend()
