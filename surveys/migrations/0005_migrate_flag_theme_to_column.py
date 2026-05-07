from django.db import migrations


FLAG_THEME_NAMES = ("flag for follow-up", "flag", "flagged", "follow-up")


def flag_theme_to_column(apps, schema_editor):
    """Carry over old "Flag for follow-up" tags into Response.is_flagged.

    Bite B in the triage handoff promotes flag from a sentinel theme to a
    proper column on Response. For surveys that already used the old
    sentinel-theme approach, this migration:
      1. Sets ``is_flagged=True`` on every response tagged with a theme
         whose name (case-insensitive) matches a flag sentinel.
      2. Deletes those theme rows so they don't show up in dashboards.
    """
    Theme = apps.get_model("surveys", "Theme")
    flag_themes = Theme.objects.filter(name__iexact="Flag for follow-up")
    for theme in flag_themes:
        for rt in theme.responsetheme_set.select_related("response"):
            r = rt.response
            r.is_flagged = True
            r.save(update_fields=["is_flagged"])
        theme.delete()


def column_to_flag_theme(apps, schema_editor):
    """Reverse: recreate a 'Flag for follow-up' theme per survey and tag
    each flagged response with it. Best-effort — for migration symmetry."""
    Survey = apps.get_model("surveys", "Survey")
    Theme = apps.get_model("surveys", "Theme")
    ResponseTheme = apps.get_model("surveys", "ResponseTheme")
    Response = apps.get_model("surveys", "Response")
    for survey in Survey.objects.all():
        flagged = Response.objects.filter(
            question__survey=survey, is_flagged=True
        )
        if not flagged.exists():
            continue
        theme, _ = Theme.objects.get_or_create(
            survey=survey, name="Flag for follow-up"
        )
        for r in flagged:
            ResponseTheme.objects.get_or_create(response=r, theme=theme)


class Migration(migrations.Migration):

    dependencies = [("surveys", "0004_response_is_flagged")]

    operations = [
        migrations.RunPython(flag_theme_to_column, column_to_flag_theme),
    ]
