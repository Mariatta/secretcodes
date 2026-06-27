"""Regenerate (or verify) the committed content_planner JSON Schema files.

The schemas are derived from the models, so this keeps the committed files in
``content_planner/schemas/`` in sync with channel/status changes. CI runs it
with ``--check`` to fail the build if the model changed but the schema didn't.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from content_planner import schemas

FILES = {
    "create_from_chat.schema.json": "build_create_from_chat_schema",
    "export.schema.json": "build_export_schema",
}


def _render(builder_name):
    return json.dumps(getattr(schemas, builder_name)(), indent=2) + "\n"


class Command(BaseCommand):
    help = "Regenerate content_planner JSON Schema files from the models."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check",
            action="store_true",
            help="Exit non-zero if a committed schema is out of date.",
        )

    def handle(self, *args, check=False, **options):
        stale = []
        for name, builder_name in FILES.items():
            path = schemas.SCHEMA_DIR / name
            content = _render(builder_name)
            if check:
                current = path.read_text() if path.exists() else None
                if current != content:
                    stale.append(name)
            else:
                path.write_text(content)
                self.stdout.write(f"wrote {path}")
        if stale:
            raise CommandError(
                "Out-of-date schema(s): "
                + ", ".join(stale)
                + ". Run `./manage.py rebuild_content_schemas`."
            )
