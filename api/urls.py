from django.urls import include, path
from rest_framework.routers import DefaultRouter

from accounts.views import ForgotPasswordAPIView, LoginAPIView, LoginVerifyOTPAPIView, ResendOTPAPIView, ResetPasswordAPIView, VerifyOTPAPIView
from courses.views import midtrans_notification_view

from .views import (
    CourseViewSet,
    EnrollmentViewSet,
    LogoutAPI,
    MeAPI,
    RegisterAPI,
    SupportChatAPIView,
    SupportKnowledgeDocumentViewSet,
)

router = DefaultRouter()
router.register("courses", CourseViewSet, basename="api-courses")
router.register("enrollments", EnrollmentViewSet, basename="api-enrollments")
router.register("support/knowledge", SupportKnowledgeDocumentViewSet, basename="api-support-knowledge")

urlpatterns = [
    path("login/", LoginAPIView.as_view(), name="api-login"),
    path("login/verify-otp/", LoginVerifyOTPAPIView.as_view(), name="api-login-verify-otp"),
    path("forgot-password/", ForgotPasswordAPIView.as_view(), name="api-forgot-password"),
    path("verify-otp/", VerifyOTPAPIView.as_view(), name="api-verify-otp"),
    path("reset-password/", ResetPasswordAPIView.as_view(), name="api-reset-password"),
    path("resend-otp/", ResendOTPAPIView.as_view(), name="api-resend-otp"),
    path("auth/register/", RegisterAPI.as_view(), name="api-register"),
    path("auth/login/", LoginAPIView.as_view(), name="api-auth-login"),
    path("auth/logout/", LogoutAPI.as_view(), name="api-logout"),
    path("auth/me/", MeAPI.as_view(), name="api-me"),
    path("support/chat/", SupportChatAPIView.as_view(), name="api-support-chat"),
    path("payments/midtrans/notification/", midtrans_notification_view, name="api-midtrans-notification"),
    path("", include(router.urls)),
]
