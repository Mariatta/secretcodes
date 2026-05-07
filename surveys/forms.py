import json
import uuid

from django import forms
from django.db import transaction
from django.forms.models import inlineformset_factory

from .models import Question, Response, Survey, Theme  # noqa: F401


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
        raise ValueError(f"Unknown question type: {question.type}")

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
        fields = ("title", "slug", "status")
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "slug": forms.TextInput(attrs={"class": "form-control"}),
            "status": forms.RadioSelect(attrs={"class": "btn-check"}),
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


QuestionFormSet = inlineformset_factory(
    Survey,
    Question,
    form=QuestionForm,
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
