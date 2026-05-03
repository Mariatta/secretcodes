from django.db import migrations

GROUP_NAME = "QR Slug User"
PERM_CODENAME = "create_slug_qrcode"
PERM_NAME = "Can create slug-style QR codes"


def seed_forward(apps, schema_editor):
    """Create the QR Slug User group and grant create_slug_qrcode.

    The permission row is also created here if Django's post_migrate
    signal hasn't gotten to it yet, making this migration self-sufficient.
    """
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    qrcode_ct, _ = ContentType.objects.get_or_create(
        app_label="qrcode_manager", model="qrcode"
    )
    perm, _ = Permission.objects.get_or_create(
        codename=PERM_CODENAME,
        content_type=qrcode_ct,
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
        ("qrcode_manager", "0005_alter_qrcode_options"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(seed_forward, seed_reverse),
    ]
