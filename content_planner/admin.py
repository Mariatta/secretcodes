from django.contrib import admin

from .models import (
    Asset,
    Campaign,
    ContentBoard,
    ContentCollaborator,
    ContentInvitation,
    Post,
    Tag,
)


class CollaboratorInline(admin.TabularInline):
    model = ContentCollaborator
    extra = 0
    fields = ("user", "role", "joined_at")
    readonly_fields = ("joined_at",)


class TagInline(admin.TabularInline):
    model = Tag
    extra = 0
    fields = ("name",)


@admin.register(ContentBoard)
class ContentBoardAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "slug", "timezone", "is_archived")
    list_filter = ("is_archived",)
    search_fields = ("name", "slug", "owner__username")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [CollaboratorInline, TagInline]


@admin.register(ContentInvitation)
class ContentInvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "board", "inviter", "sent_at", "accepted_at")
    list_filter = ("board",)
    search_fields = ("email", "board__name")


class PostInline(admin.TabularInline):
    model = Post
    extra = 0
    fields = ("title", "channel", "status", "scheduled_at", "anchor_offset_days")
    show_change_link = True


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "board", "slug", "event_date", "is_archived")
    list_filter = ("board", "is_archived")
    search_fields = ("name", "slug", "board__name")
    filter_horizontal = ("tags",)
    inlines = [PostInline]


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("title", "campaign", "channel", "status", "scheduled_at")
    list_filter = ("status", "channel", "campaign__board")
    search_fields = ("title", "slug", "campaign__name")
    filter_horizontal = ("assets",)
    readonly_fields = ("created_by",)

    def save_model(self, request, obj, form, change):
        """Stamp the original drafter once (the D1 ownership seam)."""
        if obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("name", "board", "kind", "status")
    list_filter = ("board", "kind", "status")
    search_fields = ("name", "board__name")


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "board")
    list_filter = ("board",)
    search_fields = ("name",)
