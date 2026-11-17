from django.db import migrations


def create_default_rule(apps, schema_editor):
    FollowUpRule = apps.get_model("patients", "FollowUpRule")
    FollowUpRule.objects.get_or_create(
        name="Standard follow-up",
        version="1",
        defaults={"interval_days": 21, "is_active": True},
    )


def remove_default_rule(apps, schema_editor):
    FollowUpRule = apps.get_model("patients", "FollowUpRule")
    FollowUpRule.objects.filter(
        name="Standard follow-up",
        version="1",
        interval_days=21,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("patients", "0001_initial")]

    operations = [migrations.RunPython(create_default_rule, remove_default_rule)]
