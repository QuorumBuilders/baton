from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.hashers import check_password
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import PhoneVerification
from accounts.services import issue_otp
from communications.adapters import ConsoleSMSAdapter, DeliveryUnavailable
from communications.payloads import SMSMessage
from patients.tests.helpers import make_vendor


class ConsoleSMSAdapterTests(SimpleTestCase):
    @override_settings(DEBUG=True)
    def test_complete_sms_request_is_printed_and_marked_simulated(self):
        message = SMSMessage(
            recipient="+2348012345678",
            body="Complete message body 583029",
            category="test_message",
            reference_id="sms-reference-1",
        )
        output = StringIO()
        with redirect_stdout(output):
            result = ConsoleSMSAdapter().send(message)
        rendered = output.getvalue()
        for expected in (
            message.recipient,
            message.body,
            message.category,
            message.reference_id,
            "timestamp=",
            "SIMULATED",
        ):
            self.assertIn(expected, rendered)
        self.assertEqual(result.outcome, "simulated")

    @override_settings(DEBUG=False)
    def test_console_sms_adapter_is_blocked_outside_debug(self):
        with self.assertRaises(ImproperlyConfigured):
            ConsoleSMSAdapter()

    def test_existing_sms_adapter_checks_debug_again_before_sending(self):
        with override_settings(DEBUG=True):
            adapter = ConsoleSMSAdapter()
        output = StringIO()
        with override_settings(DEBUG=False), redirect_stdout(output):
            with self.assertRaises(ImproperlyConfigured):
                adapter.send(SMSMessage("+2348012345678", "Private body 583029", "test", "test-ref"))
        self.assertEqual(output.getvalue(), "")


@override_settings(
    DEBUG=True,
    SMS_DELIVERY_BACKEND="communications.adapters.ConsoleSMSAdapter",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class OTPConsoleIntegrationTests(TestCase):
    def issue_and_capture(self, phone, purpose):
        output = StringIO()
        with patch("accounts.services.secrets.randbelow", return_value=583029):
            with redirect_stdout(output), self.captureOnCommitCallbacks(execute=True):
                verification = issue_otp(phone, purpose=purpose)
        return verification, output.getvalue()

    def test_vendor_otp_uses_general_sms_console_payload_and_stays_hashed(self):
        verification, output = self.issue_and_capture("08012345678", "vendor")
        self.assertIn("category=vendor_otp", output)
        self.assertIn("body=Your Baton vendor registration verification code is 583029", output)
        self.assertIn(f"reference_id={verification.pk}", output)
        self.assertNotEqual(verification.token_hash, "583029")
        self.assertTrue(check_password("583029", verification.token_hash))

    def test_patient_otp_uses_the_same_general_sms_console_adapter(self):
        verification, output = self.issue_and_capture("08050675448", "patient")
        self.assertIn("category=patient_otp", output)
        self.assertIn("body=Your Baton patient registration verification code is 583029", output)
        self.assertIn(f"reference_id={verification.pk}", output)
        self.assertEqual(PhoneVerification.objects.get().purpose, "patient")
        self.assertTrue(check_password("583029", verification.token_hash))

    def test_vendor_console_otp_does_not_leak_through_http_or_session(self):
        output = StringIO()
        with patch("accounts.services.secrets.randbelow", return_value=583029):
            with redirect_stdout(output), self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(reverse("accounts:register"), {
                    "phone_number": "08012345678", "business_name": "Prototype Pharmacy",
                }, follow=True)
        self.assertIn("583029", output.getvalue())
        self.assertNotContains(response, "583029")
        self.assertNotIn("583029", str(dict(self.client.session)))

    def test_patient_console_otp_does_not_leak_through_http_or_session(self):
        self.client.force_login(make_vendor())
        output = StringIO()
        with patch("accounts.services.secrets.randbelow", return_value=583029):
            with redirect_stdout(output), self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(reverse("patients:register"), {
                    "phone_number": "08050675448",
                }, follow=True)
        self.assertIn("583029", output.getvalue())
        self.assertNotContains(response, "583029")
        self.assertNotIn("583029", str(dict(self.client.session)))

    def test_transport_failure_is_sanitized_and_invalidates_the_otp_grant(self):
        with patch("accounts.services.get_delivery_backend") as backend:
            backend.return_value.send.side_effect = RuntimeError("sensitive provider payload 583029")
            with self.assertRaises(DeliveryUnavailable) as caught:
                with self.captureOnCommitCallbacks(execute=True):
                    verification = issue_otp("08012345678")
        self.assertNotIn("583029", str(caught.exception))
        verification.refresh_from_db()
        self.assertIsNotNone(verification.invalidated_at)

    @override_settings(DEBUG=False)
    def test_development_sms_transport_cannot_be_used_in_production(self):
        with self.assertRaises(ImproperlyConfigured):
            issue_otp("08012345678")
        self.assertFalse(PhoneVerification.objects.exists())
