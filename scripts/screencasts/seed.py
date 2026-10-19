"""Put the throwaway database into the state the screencasts expect.

Run with ``python manage.py shell < scripts/screencasts/seed.py`` on the
screencast database. It creates (or resets) the account the scripts sign in
with, puts it in the Expenses User and Expense Manager groups so it can
create events, and removes any events an earlier take left behind.

Environment: ``SAMPLE_USERNAME``, ``SAMPLE_PASSWORD``, ``SAMPLE_FIRST_NAME``.
"""

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from expenses.models import Event
from expenses.permissions import EXPENSE_MANAGER_GROUP, EXPENSES_USER_GROUP

USERNAME = os.environ.get("SAMPLE_USERNAME", "maya")
PASSWORD = os.environ.get("SAMPLE_PASSWORD", "screencast123")
FIRST_NAME = os.environ.get("SAMPLE_FIRST_NAME", "Maya")

User = get_user_model()

user, _ = User.objects.get_or_create(username=USERNAME)
user.first_name = FIRST_NAME
user.email = f"{USERNAME}@example.test"
user.is_active = True
user.set_password(PASSWORD)
user.save()
for name in (EXPENSES_USER_GROUP, EXPENSE_MANAGER_GROUP):
    user.groups.add(Group.objects.get(name=name))

for event in Event.objects.filter(owner=user):
    event.expenses.all().delete()
    event.delete()
