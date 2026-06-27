from django.db import migrations

GROUP_NAME = "content_planner_users"
PERM_CODENAME = "access_content_planner"
PERM_NAME = "Can access the content planner module"


def seed_forward(apps, schema_editor):
    """Create the content_planner_users group and grant the access perm.

    The permission is also created if it isn't already — Django's
    post_migrate signal usually creates Meta permissions, but it fires
    after the entire migrate command, not after each migration. The
    explicit get_or_create here makes this migration self-sufficient.

    The group name follows the ``<app_label>_users`` convention that
    ``core.permissions.grant_app_access`` looks up.
    """
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    board_ct, _ = ContentType.objects.get_or_create(
        app_label="content_planner", model="contentboard"
    )
    perm, _ = Permission.objects.get_or_create(
        codename=PERM_CODENAME,
        content_type=board_ct,
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
        ("content_planner", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(seed_forward, seed_reverse),
    ]
