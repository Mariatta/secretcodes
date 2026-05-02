from django.db import migrations

LEGACY_GROUP = "expenses_users"


def drop_legacy_group(apps, schema_editor):
    """Remove the now-unused expenses_users group.

    Access is gated by the `expenses.access_expenses` permission instead;
    the group existed only as a batch-management convenience and is no
    longer referenced by code.
    """
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=LEGACY_GROUP).delete()


def noop_reverse(apps, schema_editor):
    """No reverse — the group's recreation belongs to admin if needed."""


class Migration(migrations.Migration):
    dependencies = [
        ("expenses", "0003_alter_event_options"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(drop_legacy_group, noop_reverse),
    ]
