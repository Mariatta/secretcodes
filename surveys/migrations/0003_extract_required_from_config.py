from django.db import migrations


def extract_required_from_config(apps, schema_editor):
    """Move ``config['required']`` (if present) into the new column.

    Removes the key from ``config`` so the JSON field carries only
    type-specific settings going forward.
    """
    Question = apps.get_model("surveys", "Question")
    for q in Question.objects.all():
        config = q.config if isinstance(q.config, dict) else {}
        if "required" in config:
            q.required = bool(config.get("required", True))
            new_config = {k: v for k, v in config.items() if k != "required"}
            q.config = new_config
            q.save(update_fields=["required", "config"])


def restore_required_to_config(apps, schema_editor):
    """Reverse: write ``required=False`` back into config when the column is False.

    Required=True is the default and is implicit — no need to write it back.
    """
    Question = apps.get_model("surveys", "Question")
    for q in Question.objects.all():
        if not q.required:
            config = dict(q.config) if isinstance(q.config, dict) else {}
            config["required"] = False
            q.config = config
            q.save(update_fields=["config"])


class Migration(migrations.Migration):

    dependencies = [("surveys", "0002_question_required")]

    operations = [
        migrations.RunPython(extract_required_from_config, restore_required_to_config),
    ]
