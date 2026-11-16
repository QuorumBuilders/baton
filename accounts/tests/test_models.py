from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import User


class UserModelTests(TestCase):
    def vendor(self, phone_number="08012345678", **extra):
        return User.objects.create_user(
            phone_number=phone_number, business_name="Community Pharmacy", password="482953", **extra
        )

    def test_administrator_creation_without_vendor_fields(self):
        user = User.objects.create_superuser(username="administrator", password="Pine!Stone7quiet")
        self.assertEqual(user.account_type, User.AccountType.ADMINISTRATOR)
        self.assertIsNone(user.phone_number)
        self.assertIsNone(user.business_name)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password("Pine!Stone7quiet"))

    def test_vendor_creation_normalizes_phone_and_hashes_pin(self):
        user = self.vendor()
        self.assertEqual(user.phone_number, "+2348012345678")
        self.assertEqual(user.username, "")
        self.assertEqual(user.account_type, User.AccountType.VENDOR)
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertNotEqual(user.password, "482953")
        self.assertTrue(user.check_password("482953"))

    def test_multiple_blank_usernames_and_duplicate_business_names_are_allowed(self):
        first = self.vendor()
        second = self.vendor("08012345679")
        self.assertEqual(first.username, second.username)
        self.assertEqual(first.business_name, second.business_name)
        self.assertEqual(User.objects.count(), 2)

    def test_nonempty_username_uniqueness_is_enforced_by_database(self):
        User.objects.create_user(username="operator", account_type=User.AccountType.ADMINISTRATOR)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([
                User(username="operator", account_type=User.AccountType.ADMINISTRATOR, password="!")
            ])

    def test_phone_uniqueness_after_normalization(self):
        self.vendor()
        for phone_number in ("+2348012345678", "2348012345678", "0801 234 5678"):
            with self.subTest(phone_number=phone_number):
                with self.assertRaises(ValidationError):
                    self.vendor(phone_number)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([
                User(phone_number="+2348012345678", business_name="Different Pharmacy", password="!")
            ])

    def test_account_specific_database_constraints_cannot_be_bypassed(self):
        defaults = {
            "account_type": User.AccountType.VENDOR,
            "phone_number": "+2348012345678",
            "business_name": "Community Pharmacy",
            "password": "!",
        }
        invalid_values = (
            {"account_type": "unknown"},
            {"account_type": User.AccountType.ADMINISTRATOR, "username": ""},
            {"account_type": User.AccountType.ADMINISTRATOR, "username": "   "},
            {"phone_number": None}, {"phone_number": ""},
            {"phone_number": "08012345678"},
            {"business_name": None}, {"business_name": ""}, {"business_name": "   "},
            {"is_staff": True}, {"is_superuser": True},
        )
        for values in invalid_values:
            with self.subTest(values=values):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    User.objects.bulk_create([User(**(defaults | values))])

    def test_vendor_privilege_escalation_is_rejected_on_save_and_update(self):
        user = self.vendor()
        user.is_staff = True
        with self.assertRaises(ValidationError):
            user.save()
        for field in ("is_staff", "is_superuser"):
            with self.subTest(field=field):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    User.objects.filter(pk=user.pk).update(**{field: True})

    def test_vendor_cannot_be_created_as_superuser(self):
        with self.assertRaises(ValidationError):
            User.objects.create_superuser(
                username="vendor", account_type=User.AccountType.VENDOR,
                phone_number="08012345678", business_name="Community Pharmacy",
            )
