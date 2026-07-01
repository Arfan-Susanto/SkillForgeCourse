from django.contrib import admin

from .models import CartPayment, Course


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "price", "instructor", "created_at")
    list_filter = ("created_at",)
    search_fields = ("title", "description", "instructor__username")
    list_editable = ("instructor",)


@admin.register(CartPayment)
class CartPaymentAdmin(admin.ModelAdmin):
    list_display = ("order_id", "user", "gross_amount", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("order_id", "user__username", "user__email")
