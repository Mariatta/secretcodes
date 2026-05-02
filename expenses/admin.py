from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    Category,
    Event,
    Expense,
    ExpenseInvitation,
    ExpenseShare,
    Participant,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "modified_date")
    search_fields = ("name",)


class ParticipantInline(admin.TabularInline):
    model = Participant
    extra = 1
    fields = (
        "user",
        "display_name",
        "invited_email",
        "role",
        "joined_at",
        "payment_info",
    )


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "owner",
        "base_currency",
        "start_date",
        "end_date",
        "is_archived",
    )
    list_filter = ("is_archived", "base_currency")
    search_fields = ("name", "owner__username")
    inlines = [ParticipantInline]
    actions = ["recompute_base_amounts"]

    @admin.action(description="Recompute base amounts (after fx_rates change)")
    def recompute_base_amounts(self, request, queryset):
        """Re-save every expense in the selected events.

        Expense.save() recomputes `base_amount` from
        `event.fx_rates[original_currency]`. Use this after editing
        `fx_rates` on an event so historical expenses pick up the new
        conversion. Note: shares are NOT re-derived — manually re-edit
        each expense if you want shares to reflect new totals.
        """
        total = 0
        for event in queryset:
            for expense in event.expenses.all():
                expense.save()
                total += 1
        self.message_user(request, f"Recomputed base amounts on {total} expenses.")


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("display_name", "event", "user", "role", "joined_at")
    list_filter = ("role", "event")
    search_fields = ("display_name", "invited_email", "user__username")


class ExpenseShareInline(admin.TabularInline):
    """Full add/edit/remove of shares from the admin.

    The user-facing expense form does equal-split automatically; the admin
    is the manual-override surface. All fields are editable here so admins
    can fix split mistakes, add a forgotten participant, or remove a row.
    `share_amount` is required at model level — the form will reject blank.
    """

    model = ExpenseShare
    extra = 0
    fields = ("participant", "share_amount", "reimbursed")


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = (
        "description",
        "event",
        "payer",
        "category",
        "original_amount",
        "original_currency",
        "base_amount",
        "paid_at",
    )
    list_filter = ("event", "category", "paid_at")
    search_fields = ("description", "event__name")
    readonly_fields = ("download_receipt_link",)
    inlines = [ExpenseShareInline]

    @admin.display(description="Download receipt")
    def download_receipt_link(self, obj):
        """Render a download link for the encrypted receipt, if any.

        Storage's `url()` returns None so the standard ClearableFileInput
        link is suppressed. This readonly field gives admins a working
        link routed through the receipt_download view.
        """
        if not obj or not obj.pk or not obj.receipt:
            return "—"
        url = reverse(
            "expenses:receipt_download",
            kwargs={"event_id": obj.event_id, "expense_id": obj.pk},
        )
        label = obj.receipt_original_filename or "download"
        return format_html('<a href="{}" target="_blank">{}</a>', url, label)


@admin.register(ExpenseShare)
class ExpenseShareAdmin(admin.ModelAdmin):
    list_display = ("expense", "participant", "share_amount", "reimbursed")
    list_filter = ("reimbursed", "expense__event")
    search_fields = ("expense__description", "participant__display_name")


@admin.register(ExpenseInvitation)
class ExpenseInvitationAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "event",
        "inviter",
        "sent_at",
        "accepted_at",
        "creation_date",
    )
    list_filter = ("event", "accepted_at")
    search_fields = ("email", "display_name", "event__name")
    readonly_fields = ("key", "sent_at", "accepted_at")
