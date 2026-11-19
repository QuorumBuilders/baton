import os
import runpy
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.staticfiles import finders
from django.core.exceptions import ImproperlyConfigured
from django.templatetags.static import static
from django.test import SimpleTestCase
from django.urls import reverse


class LandingPageTests(SimpleTestCase):
    def test_landing_page_is_public_and_uses_base_template(self):
        response = self.client.get(reverse("core:landing"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/landing.html")
        self.assertTemplateUsed(response, "base.html")
        self.assertContains(response, "Baton")
        self.assertContains(response, '<main id="main-content" tabindex="-1">')

    def test_landing_page_links_to_available_static_assets(self):
        response = self.client.get(reverse("core:landing"))

        for asset in ("core/css/site.css", "core/images/baton.svg"):
            with self.subTest(asset=asset):
                self.assertContains(response, static(asset))
                self.assertIsNotNone(finders.find(asset))


class AdminRouteTests(SimpleTestCase):
    def test_admin_requires_authentication(self):
        response = self.client.get(reverse("admin:index"))

        self.assertRedirects(
            response,
            f"{reverse('admin:login')}?next={reverse('admin:index')}",
        )

    def test_admin_login_is_available(self):
        response = self.client.get(reverse("admin:login"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "admin/login.html")
        self.assertContains(response, 'name="csrfmiddlewaretoken"')


class EnvironmentSettingsTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.project_dir = Path(directory.name)
        self.settings_path = self.project_dir / "config" / "settings.py"
        self.settings_path.parent.mkdir()
        copyfile(
            Path(__file__).resolve().parent.parent / "config" / "settings.py",
            self.settings_path,
        )

    def test_project_root_dotenv_file_is_loaded(self):
        (self.project_dir / ".env").write_text(
            "DJANGO_SECRET_KEY=test-only-file-secret\n"
            "DJANGO_DEBUG=True\n"
            "DJANGO_ALLOWED_HOSTS=file.example, localhost\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {}, clear=True):
            configuration = runpy.run_path(self.settings_path)

        self.assertEqual(configuration["SECRET_KEY"], "test-only-file-secret")
        self.assertIs(configuration["DEBUG"], True)
        self.assertEqual(configuration["ALLOWED_HOSTS"], ["file.example", "localhost"])

    def test_process_environment_takes_precedence_over_dotenv(self):
        (self.project_dir / ".env").write_text(
            "DJANGO_SECRET_KEY=test-only-file-secret\n"
            "DJANGO_DEBUG=True\n"
            "DJANGO_ALLOWED_HOSTS=file.example\n",
            encoding="utf-8",
        )
        environment = {
            "DJANGO_SECRET_KEY": "test-only-process-secret",
            "DJANGO_DEBUG": "False",
            "DJANGO_ALLOWED_HOSTS": "process.example",
        }
        with patch.dict(os.environ, environment, clear=True):
            configuration = runpy.run_path(self.settings_path)

        self.assertEqual(configuration["SECRET_KEY"], "test-only-process-secret")
        self.assertIs(configuration["DEBUG"], False)
        self.assertEqual(configuration["ALLOWED_HOSTS"], ["process.example"])

    def test_secret_key_is_required(self):
        for environment in ({}, {"DJANGO_SECRET_KEY": "   "}):
            with self.subTest(environment=environment):
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaisesMessage(ImproperlyConfigured, "DJANGO_SECRET_KEY"):
                        runpy.run_path(self.settings_path)

    def test_false_debug_value_and_comma_separated_hosts(self):
        environment = {
            "DJANGO_SECRET_KEY": "test-only-secret",
            "DJANGO_DEBUG": " False ",
            "DJANGO_ALLOWED_HOSTS": "example.com, localhost , ,",
        }
        with patch.dict(os.environ, environment, clear=True):
            configuration = runpy.run_path(self.settings_path)

        self.assertIs(configuration["DEBUG"], False)
        self.assertEqual(configuration["ALLOWED_HOSTS"], ["example.com", "localhost"])
        self.assertTrue(configuration["SESSION_COOKIE_SECURE"])
        self.assertTrue(configuration["CSRF_COOKIE_SECURE"])

    def test_invalid_debug_value_is_rejected(self):
        environment = {
            "DJANGO_SECRET_KEY": "test-only-secret",
            "DJANGO_DEBUG": "invalid",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesMessage(ImproperlyConfigured, "DJANGO_DEBUG"):
                runpy.run_path(self.settings_path)

    def test_patient_registration_lifetime_defaults_to_30_minutes_and_can_be_configured(self):
        environment = {"DJANGO_SECRET_KEY": "test-only-secret"}
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(runpy.run_path(self.settings_path)["PATIENT_REGISTRATION_TTL_SECONDS"], 1800)
        environment["PATIENT_REGISTRATION_TTL_SECONDS"] = "1200"
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(runpy.run_path(self.settings_path)["PATIENT_REGISTRATION_TTL_SECONDS"], 1200)

    def test_invalid_patient_registration_lifetime_is_rejected(self):
        for value in ("0", "-1", "invalid"):
            with self.subTest(value=value):
                environment = {"DJANGO_SECRET_KEY": "test-only-secret", "PATIENT_REGISTRATION_TTL_SECONDS": value}
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaisesMessage(ImproperlyConfigured, "PATIENT_REGISTRATION_TTL_SECONDS"):
                        runpy.run_path(self.settings_path)
