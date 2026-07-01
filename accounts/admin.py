from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import InstructorApplication, OTP, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "role", "is_staff", "is_active")
    list_filter = ("is_staff", "is_active")
    search_fields = ("username", "email")


@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "expires_at", "is_verified", "is_used", "failed_attempts")
    list_filter = ("is_verified", "is_used", "created_at", "expires_at")
    search_fields = ("user__email", "user__username")
    readonly_fields = ("created_at", "verified_at")


@admin.register(InstructorApplication)
class InstructorApplicationAdmin(admin.ModelAdmin):
    list_display = ("user", "full_name", "status", "reviewed_by", "reviewed_at", "created_at")
    list_filter = ("status", "created_at", "reviewed_at")
    search_fields = ("user__username", "user__email", "full_name", "headline")
    readonly_fields = ("created_at", "updated_at", "reviewed_at")
