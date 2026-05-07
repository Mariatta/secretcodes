from django.db import migrations

SURVEYS_USER_GROUP = "Surveys User"
COLLABORATOR_GROUP = "Survey Collaborator"
ACCESS_PERM = "access_surveys"
CREATE_PERM = "create_surveys"
CREATE_PERM_NAME = "Can create new surveys"


def seed_forward(apps, schema_editor):
    """Set up the new permission/group split:

    - ``access_surveys`` (existing) — required for any creator-side surface.
    - ``create_surveys`` (new) — required to start a fresh survey.

    Owners (``Surveys User`` group) get both. Invited collaborators
    (``Survey Collaborator`` group) get only ``access_surveys`` — they can
    edit the survey they were invited to but cannot create new ones.
    """
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    survey_ct, _ = ContentType.objects.get_or_create(
        app_label="surveys", model="survey"
    )

    access_perm = Permission.objects.filter(
        codename=ACCESS_PERM, content_type=survey_ct
    ).first()
    create_perm, _ = Permission.objects.get_or_create(
        codename=CREATE_PERM,
        content_type=survey_ct,
        defaults={"name": CREATE_PERM_NAME},
    )

    surveys_user, _ = Group.objects.get_or_create(name=SURVEYS_USER_GROUP)
    if access_perm:
        surveys_user.permissions.add(access_perm)
    surveys_user.permissions.add(create_perm)

    collaborator, _ = Group.objects.get_or_create(name=COLLABORATOR_GROUP)
    if access_perm:
        collaborator.permissions.add(access_perm)


def seed_reverse(apps, schema_editor):
    """Remove the collaborator group and detach the create perm from the
    surveys-user group; the perm itself is managed by Django."""
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    Group.objects.filter(name=COLLABORATOR_GROUP).delete()

    survey_ct = ContentType.objects.filter(app_label="surveys", model="survey").first()
    if survey_ct is None:
        return
    create_perm = Permission.objects.filter(
        codename=CREATE_PERM, content_type=survey_ct
    ).first()
    if create_perm is None:
        return
    surveys_user = Group.objects.filter(name=SURVEYS_USER_GROUP).first()
    if surveys_user is not None:
        surveys_user.permissions.remove(create_perm)


class Migration(migrations.Migration):

    dependencies = [
        ("surveys", "0008_alter_survey_options_surveyinvitation_and_more"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(seed_forward, seed_reverse),
    ]
