from django.db import migrations

GROUP_NAME = "Expenses User"
PERM_CODENAME = "access_expenses"
PERM_NAME = "Can access the expenses module"


def seed_forward(apps, schema_editor):
    """Create the Expenses User group and grant the access_expenses perm.

    The permission is also created if it isn't already — Django's
    post_migrate signal usually creates Meta permissions, but it fires
    after the entire migrate command, not after each migration. The
    explicit get_or_create here makes this migration self-sufficient.
    """
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    event_ct, _ = ContentType.objects.get_or_create(app_label="expenses", model="event")
    perm, _ = Permission.objects.get_or_create(
        codename=PERM_CODENAME,
        content_type=event_ct,
        defaults={"name": PERM_NAME},
    )
    group, _ = Group.objects.get_or_create(name=GROUP_NAME)
    group.permissions.add(perm)


def seed_reverse(apps, schema_editor):
    """Remove the group; leave the permission alone (managed by Django)."""
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=GROUP_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("expenses", "0004_drop_legacy_group"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(seed_forward, seed_reverse),
    ]
