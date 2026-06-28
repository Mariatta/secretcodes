import json
import uuid

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms.models import BaseInlineFormSet, inlineformset_factory

from .models import (  # noqa: F401
    QUESTION_HARD_LIMIT,
    Question,
    Response,
    Survey,
    SurveyCollaborator,
    SurveyInvitation,
    Theme,
)

User = get_user_model()

RATING_DEFAULT_MAX = 5
NPS_MAX = 10


class SurveyResponseForm(forms.Form):
    """Dynamically builds one form field per Question on the given Survey.

    Field name convention is ``q{question.id}`` so cleaned data can be
    walked alongside ``survey.questions`` without ambiguity. Validation
    of value shapes against ``Question.type`` lives here, not on the
    Response model.
    """

    def __init__(self, *args, survey: Survey, **kwargs):
        super().__init__(*args, **kwargs)
        self.survey = survey
        self.questions = list(survey.questions.all().order_by("order"))
        for question in self.questions:
            field_name = f"q{question.id}"
            self.fields[field_name] = self._build_field(question)

    @staticmethod
    def _scale_choices(values: range, labels: dict) -> list[tuple[str, str]]:
        """Render the label if provided, otherwise the bare number.

        The submitted *value* is still the number (so aggregations work
        unchanged); only the *display* string differs.
        """
        out = []
        for i in values:
            label = labels.get(str(i)) if labels else None
            out.append((str(i), label if label else str(i)))
        return out

    def _build_field(self, question: Question) -> forms.Field:
        required = question.required
        label = question.text
        labels = question.config.get("labels") or {}
        if question.type == Question.Type.RATING:
            max_value = int(question.config.get("max", RATING_DEFAULT_MAX))
            return forms.ChoiceField(
                label=label,
                choices=self._scale_choices(range(1, max_value + 1), labels),
                widget=forms.RadioSelect,
                required=required,
            )
        if question.type == Question.Type.MULTI_SELECT:
            raw_choices = question.config.get("choices", [])
            choices = [(c, c) for c in raw_choices]
            return forms.MultipleChoiceField(
                label=label,
                choices=choices,
                widget=forms.CheckboxSelectMultiple,
                required=required,
            )
        if question.type == Question.Type.NPS:
            """NPS shows bare numbers in the row; any configured labels are
            rendered as min/max anchors below the row by the template, not
            inside the choice text — keeps the inline layout uniform."""
            return forms.ChoiceField(
                label=label,
                choices=[(str(i), str(i)) for i in range(NPS_MAX + 1)],
                widget=forms.RadioSelect,
                required=required,
            )
        if question.type == Question.Type.OPEN_TEXT:
            return forms.CharField(
                label=label,
                widget=forms.Textarea(attrs={"rows": 4}),
                required=required,
                strip=True,
            )
        if question.type == Question.Type.YES_NO:
            return forms.ChoiceField(
                label=label,
                choices=[("yes", "Yes"), ("no", "No")],
                widget=forms.RadioSelect(attrs={"class": "btn-check"}),
                required=required,
            )
        raise ValueError(f"Unknown question type: {question.type}")  # pragma: no cover

    @staticmethod
    def _coerce_value(question: Question, raw):
        """Map a cleaned form value to the JSON shape stored on Response."""
        if question.type in (Question.Type.RATING, Question.Type.NPS):
            return int(raw) if raw not in (None, "") else None
        if question.type == Question.Type.MULTI_SELECT:
            return list(raw) if raw else []
        if question.type == Question.Type.YES_NO:
            return raw == "yes" if raw else None
        return raw

    @transaction.atomic
    def save(self) -> uuid.UUID:
        """Write one Response row per answered question.

        Empty/skipped optional questions produce no row — keeps aggregates
        honest. Returns the submission_uuid that groups all rows from this
        fill.
        """
        submission_uuid = uuid.uuid4()
        for question in self.questions:
            raw = self.cleaned_data.get(f"q{question.id}")
            value = self._coerce_value(question, raw)
            if value in (None, "", []):
                continue
            Response.objects.create(
                question=question,
                submission_uuid=submission_uuid,
                value=value,
            )
        return submission_uuid


class SurveyForm(forms.ModelForm):
    """Top-level survey fields editable in the builder."""

    class Meta:
        model = Survey
        fields = ("title", "slug", "description", "status")
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "slug": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": (
                        "A short paragraph inviting people in. Markdown supported "
                        "(bold, italic, links, lists)."
                    ),
                }
            ),
            "status": forms.RadioSelect(attrs={"class": "btn-check"}),
        }
        help_texts = {
            "description": "Optional. Shown above the questions on the respondent page.",
        }


class QuestionForm(forms.ModelForm):
    """One row in the question formset.

    ``config`` is rendered as a JSON textarea — type-specific richer UI
    can come later. Empty input coerces to ``{}``.

    Type renders as a row of clickable colored pills (RadioSelect with
    ``btn-check``) so the question type is part of the visual scan, not
    buried in a dropdown.
    """

    type = forms.ChoiceField(
        choices=Question.Type.choices,
        required=True,
        widget=forms.RadioSelect(attrs={"class": "btn-check"}),
    )

    class Meta:
        model = Question
        fields = ("order", "text", "type", "config", "required")
        widgets = {
            "order": forms.HiddenInput(),
            "text": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Question"}
            ),
            "config": forms.Textarea(
                attrs={
                    "class": "form-control font-monospace",
                    "rows": 2,
                    "placeholder": '{"max": 5}  or  {"choices": ["a", "b"]}',
                }
            ),
            "required": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def has_changed(self):
        """Treat extras with empty text as empty rows.

        Drag-reordering / Add-question JS sets ``order`` to the row's
        position on the page even before the user types anything; that
        would otherwise mark the row as changed and pull it into
        validation. A row only counts as real once the user has typed
        the question text.
        """
        if not self.instance.pk:
            text = (self.data.get(self.add_prefix("text")) or "").strip()
            if not text:
                return False
        return super().has_changed()

    def validate_unique(self):
        self._validate_uniqueness_excluding_order(self.instance.validate_unique)

    def validate_constraints(self):
        self._validate_uniqueness_excluding_order(self.instance.validate_constraints)

    def _validate_uniqueness_excluding_order(self, validator):
        """Run a per-form uniqueness validator with ``order`` excluded.

        The builder reassigns every row's ``order`` on save (shifting existing
        rows aside first), so a client-side reorder legitimately submits
        ``order`` values still held by sibling rows at validation time. Django
        6.0 runs the ``(survey, order)`` ``UniqueConstraint`` per-form against
        the DB, which rejected valid swaps. Excluding ``order`` here allows the
        swap; ``_get_validation_exclusions`` is left untouched, so the formset
        still rejects two submitted rows sharing an order, and the DB constraint
        guards the committed state.
        """
        exclude = self._get_validation_exclusions()
        exclude.add("order")
        try:
            validator(exclude=exclude)
        except forms.ValidationError as exc:  # pragma: no cover - order is the
            # only uniqueness on Question, so excluding it leaves nothing to
            # raise here; kept to surface any future non-order constraint.
            self._update_errors(exc)

    def clean_config(self):
        """Allow blank to mean ``{}``; otherwise require parseable JSON object."""
        raw = self.cleaned_data.get("config")
        if raw in (None, "", {}):
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise forms.ValidationError(f"config must be valid JSON: {exc}")
        if not isinstance(parsed, dict):
            raise forms.ValidationError("config must be a JSON object")
        return parsed


class BaseQuestionFormSet(BaseInlineFormSet):
    """Adds the ``QUESTION_HARD_LIMIT`` cap on top of standard inline-formset behavior."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = 0
        for form in self.forms:
            if self._should_delete_form(form):
                continue
            if form.instance.pk or (form.cleaned_data.get("text") or "").strip():
                kept += 1
        if kept > QUESTION_HARD_LIMIT:
            raise forms.ValidationError(
                f"A survey can have at most {QUESTION_HARD_LIMIT} questions "
                f"(this one has {kept}). Remove some before saving."
            )


QuestionFormSet = inlineformset_factory(
    Survey,
    Question,
    form=QuestionForm,
    formset=BaseQuestionFormSet,
    extra=0,
    can_delete=True,
)


class SurveyImportForm(forms.Form):
    """Upload a markdown file describing a survey."""

    markdown_file = forms.FileField(
        label="Markdown file",
        help_text=(
            "Upload a .md or .txt file with the survey definition. "
            "Imports the survey and its questions; responses are not imported."
        ),
    )


class ThemeForm(forms.ModelForm):
    """Action-item draft area on the theme detail page."""

    class Meta:
        model = Theme
        fields = ("name", "tag", "action_item", "priority", "status")
        labels = {
            "name": "Theme name",
            "tag": "Tag",
            "action_item": "What will we do about this?",
            "priority": "Priority",
            "status": "Status",
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "tag": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "scheduling, venue, …"}
            ),
            "action_item": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "e.g. Add 30-minute breaks between tracks.",
                }
            ),
            "priority": forms.RadioSelect(attrs={"class": "btn-check"}),
            "status": forms.RadioSelect(attrs={"class": "btn-check"}),
        }


class SurveyInvitationForm(forms.Form):
    """Owner-only form to invite a collaborator to a survey by email."""

    email = forms.EmailField(label="Email")

    def __init__(self, *args, survey, inviter, **kwargs):
        super().__init__(*args, **kwargs)
        self.survey = survey
        self.inviter = inviter

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if self.inviter.email and self.inviter.email.lower() == email:
            raise ValidationError(
                "You're the survey owner — no need to invite yourself."
            )
        already_invited = SurveyInvitation.objects.filter(
            survey=self.survey, email__iexact=email, accepted_at__isnull=True
        ).exists()
        if already_invited:
            raise ValidationError(
                "There's already a pending invitation for this email on this survey."
            )
        already_collaborator = self.survey.collaborators.filter(
            user__email__iexact=email
        ).exists()
        if already_collaborator:
            raise ValidationError(
                "This person is already a collaborator on this survey."
            )
        return email

    @transaction.atomic
    def save(self):
        return SurveyInvitation.create(
            survey=self.survey,
            email=self.cleaned_data["email"],
            inviter=self.inviter,
        )


class SurveyAcceptInviteSignupForm(forms.Form):
    """Sign-up form rendered when an invitee has no account yet.

    Email is fixed to the invitation's email (not editable). Collects
    username + password, creates a fresh User, returns it so the view
    can ``login()`` and proceed.
    """

    username = forms.CharField(
        label="Username",
        max_length=150,
        help_text="Used to log in. Letters, digits and @/./+/-/_ only.",
    )
    first_name = forms.CharField(label="First name", max_length=150, required=False)
    password1 = forms.CharField(
        label="Password", widget=forms.PasswordInput, strip=False
    )
    password2 = forms.CharField(
        label="Password (again)", widget=forms.PasswordInput, strip=False
    )

    def __init__(self, *args, email, **kwargs):
        super().__init__(*args, **kwargs)
        self.email = email

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("That username is taken.")
        return username

    def clean(self):
        cleaned = super().clean()
        if User.objects.filter(email__iexact=self.email).exists():
            raise ValidationError(
                "This email address already has an account. "
                "Please log in instead of signing up."
            )
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Passwords don't match.")
        if p1:
            try:
                validate_password(p1)
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    def save(self):
        return User.objects.create_user(
            username=self.cleaned_data["username"],
            email=self.email,
            password=self.cleaned_data["password1"],
            first_name=self.cleaned_data.get("first_name", ""),
        )
