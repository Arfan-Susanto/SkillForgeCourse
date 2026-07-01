from django.contrib import admin

from .models import Enrollment, Invoice, RevenueLedger


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("user", "course", "granted_via", "amount_paid", "created_at")
    list_filter = ("granted_via", "created_at")
    search_fields = ("user__username", "course__title")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "user", "amount_paid", "payment_method", "status", "created_at")
    list_filter = ("payment_method", "status", "created_at")
    search_fields = ("invoice_number", "user__username", "courses__title")


@admin.register(RevenueLedger)
class RevenueLedgerAdmin(admin.ModelAdmin):
    list_display = ("payment", "course", "instructor", "gross_amount", "payment_status", "paid_at")
    list_filter = ("payment_status", "paid_at", "created_at")
    search_fields = ("payment__order_id", "user__username", "course__title", "instructor__username")

