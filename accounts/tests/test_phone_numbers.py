from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from accounts.phone_numbers import local_phone_number, normalize_mobile_number, normalize_phone_number


class PhoneNumberTests(SimpleTestCase):
    def test_local_nigerian_number(self):
        self.assertEqual(normalize_phone_number("08012345678"), "+2348012345678")

    def test_current_nigerian_fixed_line_number(self):
        self.assertEqual(normalize_phone_number("02012345678"), "+2342012345678")

    def test_international_representations_share_canonical_format(self):
        for value in (
            "+2348012345678", "2348012345678", "002348012345678",
            " +234 (801) 234-5678 ", "0801 234 5678",
        ):
            with self.subTest(value=value):
                self.assertEqual(normalize_phone_number(value), "+2348012345678")

    def test_invalid_or_unsupported_numbers_are_rejected(self):
        for value in (
            None, "", "080123", "080123456789", "8012345678",
            "+12025550123", "+2349991234567", "080CALLNOW", "++2348012345678",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    normalize_phone_number(value)

    def test_mobile_only_normalization_and_local_display(self):
        self.assertEqual(normalize_mobile_number("08050675448"), "+2348050675448")
        self.assertEqual(local_phone_number("+2348050675448"), "08050675448")
        with self.assertRaises(ValidationError):
            normalize_mobile_number("02012345678")
