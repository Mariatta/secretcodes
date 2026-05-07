from django.db import migrations

GROUP_NAME = "Surveys User"
PERM_CODENAME = "access_surveys"
PERM_NAME = "Can access the surveys module"


def seed_forward(apps, schema_editor):
    """Create the Surveys User group and grant the access_surveys perm.

    The permission is also created if it isn't already — Django's
    post_migrate signal usually creates Meta permissions, but it fires
    after the entire migrate command, not after each migration. The
    explicit get_or_create here makes this migration self-sufficient.
    """
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    survey_ct, _ = ContentType.objects.get_or_create(
        app_label="surveys", model="survey"
    )
    perm, _ = Permission.objects.get_or_create(
        codename=PERM_CODENAME,
        content_type=survey_ct,
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
        ("surveys", "0006_alter_survey_options"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(seed_forward, seed_reverse),
    ]
