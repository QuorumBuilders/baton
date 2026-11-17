import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from patients.models import (
    BloodPressureMeasurement,
    FollowUp,
    FollowUpRule,
    VendorPatient,
)
from patients.services import (
    associate_existing_patient,
    automatic_proposal,
    proposal_snapshot,
    record_measurement,
)
from patients.views import DRAFTS_KEY

from .helpers import make_patient, make_vendor


def save_measurement(patient, vendor, *, operation_id=None, manual_date=None, pulse=72):
    rule, proposed = automatic_proposal()
    return record_measurement(
        patient_id=patient.pk,
        vendor=vendor,
        values={"systolic": 120, "diastolic": 80, "pulse": pulse},
        operation_id=operation_id or uuid.uuid4(),
        expected_proposal=proposal_snapshot(rule, proposed),
        manual_date=manual_date,
    )


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class PatientAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first_vendor = make_vendor()
        cls.second_vendor = make_vendor("08012345679", "Second Pharmacy")
        cls.unrelated_vendor = make_vendor("08012345670", "Unrelated Pharmacy")
        cls.patient = make_patient(vendor=cls.first_vendor)

    def test_vendor_list_and_direct_urls_only_expose_associated_patients(self):
        other_patient = make_patient("08050675449", vendor=self.second_vendor)
        self.client.force_login(self.first_vendor)
        response = self.client.get(reverse("patients:list"))
        self.assertContains(response, self.patient.first_name)
        self.assertNotContains(response, other_patient.local_phone)
        for route in ("detail", "new_measurement", "followup_history"):
            with self.subTest(route=route):
                self.assertEqual(
                    self.client.get(reverse(f"patients:{route}", args=[other_patient.pk])).status_code,
                    404,
                )

    def test_newly_associated_vendor_sees_complete_attributed_history(self):
        measurement = save_measurement(self.patient, self.first_vendor)
        associate_existing_patient(
            self.second_vendor, self.patient, patient_agreed=True
        )
        self.client.force_login(self.second_vendor)
        response = self.client.get(reverse("patients:detail", args=[self.patient.pk]))
        self.assertContains(response, "120/80 mmHg")
        self.assertContains(response, self.first_vendor.business_name)
        measurement.refresh_from_db()
        self.assertEqual(measurement.recording_vendor, self.first_vendor)

    def test_administrator_and_unrelated_vendor_cannot_use_vendor_patient_views(self):
        administrator = make_vendor("08012345671", "Temporary")
        administrator.account_type = "administrator"
        administrator.username = "operator"
        administrator.phone_number = None
        administrator.business_name = None
        administrator.save()
        for user, expected in ((self.unrelated_vendor, 404), (administrator, 403)):
            self.client.force_login(user)
            self.assertEqual(
                self.client.get(reverse("patients:detail", args=[self.patient.pk])).status_code,
                expected,
            )


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class MeasurementWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.vendor = make_vendor()
        cls.patient = make_patient(vendor=cls.vendor)

    def setUp(self):
        self.client.force_login(self.vendor)

    def test_web_workflow_reviews_values_and_default_21_day_date_before_save(self):
        response = self.client.post(
            reverse("patients:new_measurement", args=[self.patient.pk]),
            {"systolic": 118, "diastolic": 76, "pulse": ""},
        )
        operation_id = next(iter(self.client.session[DRAFTS_KEY]))
        confirm_url = reverse(
            "patients:confirm_measurement", args=[self.patient.pk, operation_id]
        )
        self.assertRedirects(response, confirm_url)
        response = self.client.get(confirm_url)
        self.assertContains(response, "Once saved, this measurement cannot be edited")
        proposed_date = timezone.localdate() + timedelta(days=21)
        self.assertContains(response, date_format(proposed_date, "j M Y"))
        self.assertContains(response, "Accept proposed date")
        response = self.client.post(confirm_url, {"choice": "automatic"})
        self.assertRedirects(response, reverse("patients:detail", args=[self.patient.pk]))
        measurement = BloodPressureMeasurement.objects.get()
        self.assertEqual((measurement.systolic, measurement.diastolic), (118, 76))
        self.assertIsNone(measurement.pulse)
        self.assertEqual(measurement.recording_vendor, self.vendor)
        followup = FollowUp.objects.get()
        self.assertEqual(followup.scheduled_date, timezone.localdate() + timedelta(days=21))
        self.assertEqual(followup.followup_type, FollowUp.Type.AUTOMATIC)

    def test_invalid_values_are_rejected_server_side(self):
        for data in (
            {"systolic": 0, "diastolic": 80, "pulse": ""},
            {"systolic": 120, "diastolic": -1, "pulse": ""},
            {"systolic": 120, "diastolic": 80, "pulse": 0},
            {"systolic": 40000, "diastolic": 80, "pulse": ""},
        ):
            with self.subTest(data=data):
                response = self.client.post(
                    reverse("patients:new_measurement", args=[self.patient.pk]), data
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
        self.assertFalse(BloodPressureMeasurement.objects.exists())

    def test_saved_measurement_is_immutable(self):
        measurement = save_measurement(self.patient, self.vendor)
        measurement.systolic = 140
        with self.assertRaises(ValidationError):
            measurement.save()
        with self.assertRaises(ValidationError):
            BloodPressureMeasurement.objects.filter(pk=measurement.pk).update(systolic=140)
        with self.assertRaises(ValidationError):
            measurement.delete()
        with self.assertRaises(ValidationError):
            BloodPressureMeasurement.objects.all().delete()
        self.assertEqual(BloodPressureMeasurement.objects.get().systolic, 120)

    def test_confirmation_retry_is_idempotent(self):
        operation_id = uuid.uuid4()
        first = save_measurement(
            self.patient, self.vendor, operation_id=operation_id
        )
        second = save_measurement(
            self.patient, self.vendor, operation_id=operation_id
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(BloodPressureMeasurement.objects.count(), 1)
        self.assertEqual(FollowUp.objects.filter(status=FollowUp.Status.ACTIVE).count(), 1)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class FollowUpCoordinationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first_vendor = make_vendor()
        cls.second_vendor = make_vendor("08012345679", "Second Pharmacy")
        cls.patient = make_patient(vendor=cls.first_vendor)
        VendorPatient.objects.create(patient=cls.patient, vendor=cls.second_vendor)

    def test_measurement_by_another_vendor_fulfils_active_followup_early(self):
        first = save_measurement(self.patient, self.first_vendor)
        old_followup = first.next_followup
        second = save_measurement(self.patient, self.second_vendor, pulse=None)
        old_followup.refresh_from_db()
        self.assertEqual(old_followup.status, FollowUp.Status.FULFILLED)
        self.assertEqual(old_followup.fulfilled_by_measurement, second)
        self.assertIsNotNone(old_followup.actual_fulfilment_at)
        self.assertLess(old_followup.actual_fulfilment_at.date(), old_followup.scheduled_date)
        self.assertEqual(FollowUp.objects.filter(status=FollowUp.Status.ACTIVE).count(), 1)
        self.assertEqual(FollowUp.objects.count(), 2)

    def test_manual_date_overrides_automatic_proposal(self):
        manual_date = timezone.localdate() + timedelta(days=9)
        measurement = save_measurement(
            self.patient, self.first_vendor, manual_date=manual_date
        )
        followup = measurement.next_followup
        self.assertEqual(followup.scheduled_date, manual_date)
        self.assertEqual(followup.followup_type, FollowUp.Type.MANUAL)
        self.assertIsNone(followup.scheduling_rule)

    def test_rule_changes_do_not_rewrite_existing_followups(self):
        measurement = save_measurement(self.patient, self.first_vendor)
        followup = measurement.next_followup
        original_rule = followup.scheduling_rule
        original_date = followup.scheduled_date
        original_rule.is_active = False
        original_rule.save()
        FollowUpRule.objects.create(
            name="New interval", version="2", interval_days=14, is_active=True
        )
        followup.refresh_from_db()
        self.assertEqual(followup.scheduling_rule, original_rule)
        self.assertEqual(followup.scheduled_date, original_date)

    def test_database_prevents_two_active_followups(self):
        measurement = save_measurement(self.patient, self.first_vendor)
        with self.assertRaises(IntegrityError), transaction.atomic():
            FollowUp.objects.create(
                patient=self.patient,
                scheduled_date=timezone.localdate() + timedelta(days=10),
                followup_type=FollowUp.Type.MANUAL,
                scheduled_by=self.first_vendor,
                source_measurement=BloodPressureMeasurement.objects.create(
                    patient=self.patient,
                    recording_vendor=self.first_vendor,
                    systolic=121,
                    diastolic=81,
                ),
            )
        self.assertEqual(measurement.next_followup.status, FollowUp.Status.ACTIVE)
