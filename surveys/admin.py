from django.contrib import admin

from .models import (
    Question,
    Response,
    ResponseTheme,
    Survey,
    SurveyCollaborator,
    SurveyInvitation,
    Theme,
)


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 1
    fields = ("order", "text", "type", "config")
    ordering = ("order",)


@admin.register(Survey)
class SurveyAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "status", "slug", "creation_date")
    list_filter = ("status",)
    search_fields = ("title", "slug", "owner__username")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [QuestionInline]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("survey", "order", "type", "short_text")
    list_filter = ("type", "survey")
    search_fields = ("text", "survey__title")
    ordering = ("survey", "order")

    @admin.display(description="text")
    def short_text(self, obj):
        """Truncate question body for list view readability."""
        return obj.text if len(obj.text) <= 80 else obj.text[:77] + "…"


@admin.register(Response)
class ResponseAdmin(admin.ModelAdmin):
    list_display = ("question", "submission_uuid", "submitted_at")
    list_filter = ("question__survey", "question")
    search_fields = ("submission_uuid",)
    readonly_fields = ("submission_uuid", "submitted_at", "question", "value")
    ordering = ("-submitted_at",)

    def has_add_permission(self, request):
        """Responses are submitted via the public form, never created in admin."""
        return False


class ResponseThemeInline(admin.TabularInline):
    model = ResponseTheme
    extra = 0
    fields = ("response", "is_representative", "tagged_by", "tagged_at")
    readonly_fields = ("tagged_at",)
    autocomplete_fields = ("response",)


@admin.register(Theme)
class ThemeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "survey",
        "tag",
        "status",
        "priority",
        "mention_count",
        "has_action_item",
    )
    list_filter = ("status", "priority", "survey")
    search_fields = ("name", "tag", "action_item", "survey__title")
    inlines = [ResponseThemeInline]

    @admin.display(description="mentions")
    def mention_count(self, obj):
        return obj.responses.count()

    @admin.display(boolean=True, description="action item?")
    def has_action_item(self, obj):
        return bool(obj.action_item)


@admin.register(ResponseTheme)
class ResponseThemeAdmin(admin.ModelAdmin):
    list_display = ("response", "theme", "is_representative", "tagged_by", "tagged_at")
    list_filter = ("theme__survey", "theme", "is_representative")
    search_fields = ("theme__name",)
    autocomplete_fields = ("response", "theme", "tagged_by")
    readonly_fields = ("tagged_at",)


@admin.register(SurveyCollaborator)
class SurveyCollaboratorAdmin(admin.ModelAdmin):
    list_display = ("user", "survey", "role", "joined_at")
    list_filter = ("survey", "role")
    search_fields = ("user__username", "user__email", "survey__title")
    autocomplete_fields = ("survey", "user")
    readonly_fields = ("joined_at",)


@admin.register(SurveyInvitation)
class SurveyInvitationAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "survey",
        "inviter",
        "sent_at",
        "accepted_at",
        "creation_date",
    )
    list_filter = ("survey", "accepted_at")
    search_fields = ("email", "survey__title")
    readonly_fields = ("key", "sent_at", "accepted_at")
