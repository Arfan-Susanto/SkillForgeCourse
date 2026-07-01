from django.urls import path

from .views import (
    apply_instructor_view,
    forgot_password_view,
    login_view,
    logout_view,
    profile_view,
    register_view,
    resend_login_otp_view,
    reset_password_view,
    verify_login_otp_view,
    verify_reset_otp_view,
)

app_name = "accounts"

urlpatterns = [
    path("register/", register_view, name="register"),
    path("login/", login_view, name="login"),
    path("verify-login-otp/", verify_login_otp_view, name="verify_login_otp"),
    path("resend-login-otp/", resend_login_otp_view, name="resend_login_otp"),
    path("forgot-password/", forgot_password_view, name="forgot_password"),
    path("verify-reset-otp/", verify_reset_otp_view, name="verify_reset_otp"),
    path("reset-password/", reset_password_view, name="reset_password"),
    path("logout/", logout_view, name="logout"),
    path("profile/", profile_view, name="profile"),
    path("apply-instructor/", apply_instructor_view, name="apply_instructor"),
]
