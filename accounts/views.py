# ===============================================
# ACCOUNTS VIEWS & AUTHENTICATION LOGIC
# ===============================================
# File ini berisi semua logic untuk:
# 1. Registrasi user baru
# 2. Login dengan OTP email
# 3. Forgot password & reset password
# 4. Edit profil & ubah password
# 5. Aplikasi instructor (become a teacher)
# 6. REST API endpoints untuk authentication
#
# Sistem Auth: Berbasis OTP (One-Time Password) via email
# BUKAN password biasa, tapi 6-digit code yang dikirim ke email

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.conf import settings
from django.shortcuts import redirect, render
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .forms import (
    ChangePasswordForm,
    EditProfileForm,
    EmailLoginForm,
    ForgotPasswordRequestForm,
    InstructorApplicationForm,
    OTPVerificationForm,
    RegisterForm,
    ResetPasswordForm,
)
from .models import InstructorApplication, OTP, User
from .serializers import (
    ForgotPasswordSerializer,
    LoginOTPVerifySerializer,
    LoginSerializer,
    ResetPasswordSerializer,
    ResendOTPSerializer,
    UserSerializer,
    VerifyOTPSerializer,
)
from .utils import can_request_new_otp, get_verified_otp, issue_otp, mark_otp_used, verify_user_otp

# =============== SESSION KEYS ===============
# Key untuk menyimpan data di session (temporary storage per user)
LOGIN_OTP_SESSION_USER_ID = "login_otp_user_id"  # Simpan user ID saat OTP login
LOGIN_OTP_SESSION_EMAIL = "login_otp_email"  # Simpan email saat OTP login
PROFILE_CHANGE_PASSWORD_HASH = "profile_change_password_hash"  # Hash password baru pending
PROFILE_CHANGE_PASSWORD_OTP_AT = "profile_change_password_otp_at"  # Timestamp OTP request
PROFILE_CHANGE_PASSWORD_PENDING_TTL_SECONDS = 5 * 60  # OTP berlaku 5 menit


# =============== HELPER FUNCTIONS ===============
# ✓ Clear login OTP session data
def _clear_login_otp_session(request):
    """Bersihkan data sementara login OTP dari session"""
    request.session.pop(LOGIN_OTP_SESSION_USER_ID, None)
    request.session.pop(LOGIN_OTP_SESSION_EMAIL, None)


# ✓ Clear password change session data
def _clear_profile_change_password_session(request):
    """Bersihkan data sementara ganti password dari session"""
    request.session.pop(PROFILE_CHANGE_PASSWORD_HASH, None)
    request.session.pop(PROFILE_CHANGE_PASSWORD_OTP_AT, None)


# ✓ Get latest instructor application (any status)
def _latest_instructor_application(user):
    """Ambil aplikasi instructor terbaru (terakhir disubmit) - bisa approved/rejected/pending"""
    return InstructorApplication.objects.filter(user=user).order_by("-created_at").first()


# ✓ Get pending instructor application (only PENDING status)
def _pending_instructor_application(user):
    """Ambil aplikasi instructor yang masih pending review admin"""
    return InstructorApplication.objects.filter(user=user, status=InstructorApplication.STATUS_PENDING).first()


# ✓ Validate password change session state
def _profile_change_password_state_is_valid(request):
    """Cek apakah sesi ganti password masih valid (belum expired)
    
    Sesi expire setelah PROFILE_CHANGE_PASSWORD_PENDING_TTL_SECONDS (5 menit)
    """
    pending_hash = request.session.get(PROFILE_CHANGE_PASSWORD_HASH)
    pending_at = request.session.get(PROFILE_CHANGE_PASSWORD_OTP_AT)
    if not pending_hash or not pending_at:
        return False

    try:
        pending_at_value = float(pending_at)
    except (TypeError, ValueError):
        _clear_profile_change_password_session(request)
        return False

    expires_at = pending_at_value + PROFILE_CHANGE_PASSWORD_PENDING_TTL_SECONDS
    if timezone.now().timestamp() > expires_at:
        _clear_profile_change_password_session(request)
        messages.error(request, "Sesi ganti password sudah kedaluwarsa. Silakan ulangi dari awal.")
        return False

    return True


# ✓ Login with default backend
def _login_with_default_backend(request, user):
    """Login user dengan backend default (untuk multi-auth support)
    
    Project ini punya multiple backends (OTP, OAuth, dll)
    Jadi perlu specify backend mana yang digunakan
    """
    backend = settings.AUTHENTICATION_BACKENDS[0]
    login(request, user, backend=backend)


# ✓ Check if value looks like placeholder
def _looks_like_placeholder(value):
    """Cek apakah value terlihat seperti placeholder belum dikonfigurasi
    
    Contoh: 'replace_me', 'your_secret', 'change-me', dll
    """
    normalized = (value or "").strip().lower()
    if not normalized:
        return True

    placeholder_tokens = [
        "replace",
        "redacted",
        "example",
        "change-me",
        "changeme",
        "your_",
        "your-",
    ]
    return any(token in normalized for token in placeholder_tokens)


# ✓ Check if Google OAuth is ready
def _is_google_oauth_ready():
    """Cek apakah Google OAuth credentials sudah dikonfigurasi dengan benar
    
    Jika belum atau masih placeholder, jangan tampilkan tombol 'Login with Google'
    """
    client_id = getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "")

    if _looks_like_placeholder(client_id) or _looks_like_placeholder(client_secret):
        return False

    # Web client IDs created in Google Cloud Console end with this suffix.
    return client_id.endswith(".apps.googleusercontent.com") and bool(client_secret.strip())



# ===============================================
# REGISTRATION & LOGIN VIEWS
# ===============================================

def register_view(request):
    """
    Halaman registrasi user baru
    
    Flow:
    1. User isi form registrasi (email, password, username)
    2. Form di-validate (email unique, password strong)
    3. User baru dibuat & langsung di-login
    4. Redirect ke discovery page
    """
    if request.user.is_authenticated:
        return redirect("courses:discovery")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            _login_with_default_backend(request, user)
            messages.success(request, "Account created successfully.")
            return redirect("courses:discovery")
    else:
        form = RegisterForm()
    return render(
        request,
        "accounts/register.html",
        {
            "form": form,
            "google_oauth_ready": _is_google_oauth_ready(),
        },
    )


def login_view(request):
    """
    Halaman login dengan OTP (bukan password)
    
    Flow:
    1. User isi email & password untuk verify
    2. Jika benar, system kirim OTP 6-digit ke email
    3. User diarahkan ke halaman verifikasi OTP
    4. User isi OTP code
    5. Jika cocok, user di-login
    
    PENTING: Password hanya digunakan untuk initial verification, bukan login final
    Login final adalah via OTP email
    """
    if request.user.is_authenticated:
        return redirect("courses:discovery")

    if request.method == "POST":
        form = EmailLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            # Cek cooldown - jangan kirim OTP terlalu sering
            can_request, retry_after = can_request_new_otp(user, purpose=OTP.PURPOSE_LOGIN)
            if not can_request:
                messages.error(request, f"OTP request is on cooldown. Please wait {retry_after} seconds.")
                return render(
                    request,
                    "accounts/login.html",
                    {
                        "form": form,
                        "google_oauth_ready": _is_google_oauth_ready(),
                    },
                )

            # Kirim OTP ke email user
            issue_otp(user, purpose=OTP.PURPOSE_LOGIN)
            # Simpan user_id di session untuk next step (OTP verification)
            request.session[LOGIN_OTP_SESSION_USER_ID] = user.id
            request.session[LOGIN_OTP_SESSION_EMAIL] = user.email
            messages.success(request, "Login OTP sent. Please verify the code to continue.")
            return redirect("accounts:verify_login_otp")
    else:
        form = EmailLoginForm()
    return render(
        request,
        "accounts/login.html",
        {
            "form": form,
            "google_oauth_ready": _is_google_oauth_ready(),
        },
    )


def verify_login_otp_view(request):
    """
    Halaman verifikasi OTP login
    
    Flow:
    1. User terima OTP di email
    2. User masukkan OTP code
    3. System verifikasi code cocok atau tidak
    4. Jika cocok, user di-login & session dibersihkan
    5. Redirect ke discovery page
    
    Security: Ada rate limiting jika terlalu banyak attempt salah
    """
    if request.user.is_authenticated:
        return redirect("courses:discovery")

    # Ambil user_id dari session login sebelumnya
    user_id = request.session.get(LOGIN_OTP_SESSION_USER_ID)
    if not user_id:
        messages.info(request, "Please login with email and password first.")
        return redirect("accounts:login")

    user = User.objects.filter(id=user_id, is_active=True).first()
    if user is None:
        _clear_login_otp_session(request)
        messages.error(request, "Login session is invalid. Please try again.")
        return redirect("accounts:login")

    email = request.session.get(LOGIN_OTP_SESSION_EMAIL, user.email)

    if request.method == "POST":
        form = OTPVerificationForm(request.POST)
        if form.is_valid():
            # Verifikasi OTP yang user masukkan
            otp, message, error_code = verify_user_otp(
                user,
                form.cleaned_data["otp"],
                purpose=OTP.PURPOSE_LOGIN,
            )
            if otp is None:
                # Jika OTP attempt terlalu banyak salah, lock temporary
                if error_code == "locked":
                    messages.error(request, "Too many wrong OTP attempts. Please login again to request a new OTP.")
                    _clear_login_otp_session(request)
                    return redirect("accounts:login")

                messages.error(request, message)
                return render(request, "accounts/verify_login_otp.html", {"form": form, "email": email})

            # OTP verified! Login user
            mark_otp_used(otp)
            _clear_login_otp_session(request)
            _login_with_default_backend(request, user)
            messages.success(request, "Welcome back.")
            return redirect("courses:discovery")
    else:
        form = OTPVerificationForm()

    return render(request, "accounts/verify_login_otp.html", {"form": form, "email": email})


def resend_login_otp_view(request):
    """
    Halaman resend OTP login
    
    Jika user tidak terima OTP atau sudah expired, bisa request OTP baru
    Tapi ada cooldown - tidak boleh request terlalu sering (security)
    """
    if request.user.is_authenticated:
        return redirect("courses:discovery")

    user_id = request.session.get(LOGIN_OTP_SESSION_USER_ID)
    if not user_id:
        messages.info(request, "Please login first to request OTP.")
        return redirect("accounts:login")

    user = User.objects.filter(id=user_id, is_active=True).first()
    if user is None:
        _clear_login_otp_session(request)
        messages.error(request, "Login session is invalid. Please try again.")
        return redirect("accounts:login")

    # Cek cooldown
    can_request, retry_after = can_request_new_otp(user, purpose=OTP.PURPOSE_LOGIN)
    if not can_request:
        messages.error(request, f"OTP resend is on cooldown. Please wait {retry_after} seconds.")
        return redirect("accounts:verify_login_otp")

    # Kirim OTP baru
    issue_otp(user, purpose=OTP.PURPOSE_LOGIN)
    request.session[LOGIN_OTP_SESSION_EMAIL] = user.email
    messages.success(request, "A new login OTP has been sent to your email.")
    return redirect("accounts:verify_login_otp")


@login_required
def logout_view(request):
    """
    Logout user (destroy session & cookies)
    
    Redirect ke login page
    """
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect("accounts:login")


@login_required
def profile_view(request):
    """
    Halaman profil user - VERY COMPLEX VIEW!
    
    Fitur:
    1. Edit profil (nama, email, foto, bio)
    2. Ganti password (dengan OTP verification)
    3. Lihat aplikasi instructor (pending/approved/rejected)
    
    Multiple form handling dalam satu halaman (action-based)
    
    Flow ganti password:
    1. User isi password lama & password baru
    2. System verify password lama
    3. System kirim OTP ke email
    4. User verify OTP
    5. Password berhasil diganti
    """
    edit_form = EditProfileForm(instance=request.user)
    change_password_form = ChangePasswordForm()
    otp_form = OTPVerificationForm()
    active_tab = "edit-profile"
    show_change_password_otp = _profile_change_password_state_is_valid(request)
    profile_change_password_expires_at = None
    latest_instructor_application = _latest_instructor_application(request.user)
    pending_instructor_application = _pending_instructor_application(request.user)

    if show_change_password_otp:
        pending_at = request.session.get(PROFILE_CHANGE_PASSWORD_OTP_AT)
        if pending_at is not None:
            profile_change_password_expires_at = float(pending_at) + PROFILE_CHANGE_PASSWORD_PENDING_TTL_SECONDS
    
    if request.method == "POST":
        action = request.POST.get("action", "edit-profile")
        
        if action == "edit-profile":
            # ✓ Update profil user (nama, email, foto, bio)
            edit_form = EditProfileForm(request.POST, request.FILES, instance=request.user)
            if edit_form.is_valid():
                edit_form.save()
                messages.success(request, "Profil Anda berhasil diperbarui.")
                return redirect("accounts:profile")
            active_tab = "edit-profile"
        
        elif action == "change-password":
            # ✓ Step 1: Request ganti password (verify old password & kirim OTP)
            change_password_form = ChangePasswordForm(request.POST)
            if change_password_form.is_valid():
                current_password = change_password_form.cleaned_data["current_password"]
                new_password = change_password_form.cleaned_data["new_password"]
                
                # Verify password lama benar
                if not request.user.check_password(current_password):
                    messages.error(request, "Password saat ini tidak sesuai.")
                    show_change_password_otp = False
                else:
                    user_email = (request.user.email or "").strip()
                    if not user_email:
                        messages.error(request, "Email profil belum diisi. Tambahkan email aktif terlebih dahulu agar OTP bisa dikirim.")
                        show_change_password_otp = False
                        active_tab = "ganti-password"
                        return render(
                            request,
                            "accounts/profile.html",
                            {
                                "profile_user": request.user,
                                "edit_form": edit_form,
                                "change_password_form": change_password_form,
                                "otp_form": otp_form,
                                "active_tab": active_tab,
                                "show_change_password_otp": show_change_password_otp,
                                "profile_change_password_expires_at": profile_change_password_expires_at,
                            },
                        )

                    # Cek cooldown OTP request
                    can_request, retry_after = can_request_new_otp(request.user, purpose=OTP.PURPOSE_PASSWORD_RESET)
                    if not can_request:
                        messages.error(request, f"OTP request is on cooldown. Please wait {retry_after} seconds.")
                    else:
                        # Kirim OTP ke email
                        _clear_profile_change_password_session(request)
                        _, email_sent = issue_otp(request.user, purpose=OTP.PURPOSE_PASSWORD_RESET)
                        # Simpan password hash baru ke session (temporary)
                        request.session[PROFILE_CHANGE_PASSWORD_HASH] = make_password(new_password)
                        request.session[PROFILE_CHANGE_PASSWORD_OTP_AT] = timezone.now().timestamp()
                        show_change_password_otp = True
                        change_password_form = ChangePasswordForm()
                        if email_sent:
                            messages.success(request, "OTP sudah dikirim ke email Anda. Masukkan OTP untuk konfirmasi ganti password.")
                        else:
                            messages.warning(request, "OTP berhasil dibuat, tetapi email gagal dikirim. Cek konfigurasi email atau email profil Anda.")

            active_tab = "ganti-password"

        elif action == "verify-change-password-otp":
            # ✓ Step 2: Verify OTP & ubah password
            otp_form = OTPVerificationForm(request.POST)
            show_change_password_otp = _profile_change_password_state_is_valid(request)

            if not show_change_password_otp:
                active_tab = "ganti-password"
                return render(
                    request,
                    "accounts/profile.html",
                    {
                        "profile_user": request.user,
                        "edit_form": edit_form,
                        "change_password_form": change_password_form,
                        "otp_form": otp_form,
                        "active_tab": active_tab,
                        "show_change_password_otp": show_change_password_otp,
                    },
                )

            if otp_form.is_valid():
                # Verify OTP code
                otp, message, error_code = verify_user_otp(
                    request.user,
                    otp_form.cleaned_data["otp"],
                    purpose=OTP.PURPOSE_PASSWORD_RESET,
                )

                if otp is None:
                    messages.error(request, message)
                else:
                    # OTP verified! Update password
                    pending_password_hash = request.session.get(PROFILE_CHANGE_PASSWORD_HASH)
                    if not pending_password_hash:
                        messages.error(request, "Sesi ganti password tidak valid. Silakan ulangi dari awal.")
                        mark_otp_used(otp)
                        show_change_password_otp = False
                    else:
                        # Save new password hash
                        request.user.password = pending_password_hash
                        request.user.save(update_fields=["password"])
                        mark_otp_used(otp)
                        _clear_profile_change_password_session(request)
                        messages.success(request, "Password Anda berhasil diubah.")
                        _login_with_default_backend(request, request.user)
                        return redirect("accounts:profile")

            active_tab = "ganti-password"

        elif action == "resend-change-password-otp":
            # ✓ Resend OTP jika tidak terima
            if not _profile_change_password_state_is_valid(request):
                messages.error(request, "Tidak ada sesi ganti password aktif. Silakan isi form ganti password lagi.")
                show_change_password_otp = False
            else:
                can_request, retry_after = can_request_new_otp(request.user, purpose=OTP.PURPOSE_PASSWORD_RESET)
                if not can_request:
                    messages.error(request, f"OTP resend is on cooldown. Please wait {retry_after} seconds.")
                else:
                        _, email_sent = issue_otp(request.user, purpose=OTP.PURPOSE_PASSWORD_RESET)
                        if email_sent:
                            messages.success(request, "OTP baru sudah dikirim ke email Anda.")
                        else:
                            messages.warning(request, "OTP baru berhasil dibuat, tetapi email gagal dikirim.")
                show_change_password_otp = True

            active_tab = "ganti-password"
    
    return render(
        request,
        "accounts/profile.html",
        {
            "profile_user": request.user,
            "edit_form": edit_form,
            "change_password_form": change_password_form,
            "otp_form": otp_form,
            "active_tab": active_tab,
            "show_change_password_otp": show_change_password_otp,
            "profile_change_password_expires_at": profile_change_password_expires_at,
            "latest_instructor_application": latest_instructor_application,
            "pending_instructor_application": pending_instructor_application,
        },
    )


@login_required
def apply_instructor_view(request):
    if request.user.has_instructor_dashboard_access:
        messages.info(request, "Akun Anda sudah memiliki akses instructor dashboard.")
        return redirect("dashboard:index")

    pending_application = _pending_instructor_application(request.user)
    latest_application = _latest_instructor_application(request.user)

    if request.method == "POST":
        if pending_application is not None:
            messages.info(request, "Pengajuan instructor Anda masih menunggu review admin.")
            return redirect("accounts:apply_instructor")

        form = InstructorApplicationForm(request.POST)
        if form.is_valid():
            application = form.save(commit=False)
            application.user = request.user
            application.status = InstructorApplication.STATUS_PENDING
            application.save()
            messages.success(request, "Pengajuan instructor berhasil dikirim. Admin akan meninjaunya segera.")
            return redirect("accounts:apply_instructor")
    else:
        initial_data = {
            "full_name": request.user.get_full_name() or request.user.username,
        }

        if latest_application is not None and latest_application.status == InstructorApplication.STATUS_REJECTED:
            initial_data.update(
                {
                    "full_name": latest_application.full_name,
                    "headline": latest_application.headline,
                    "bio": latest_application.bio,
                    "portfolio_url": latest_application.portfolio_url,
                    "experience_years": latest_application.experience_years,
                    "motivation": latest_application.motivation,
                }
            )

        form = InstructorApplicationForm(initial=initial_data)

    return render(
        request,
        "accounts/apply_instructor.html",
        {
            "form": form,
            "pending_instructor_application": pending_application,
            "latest_instructor_application": latest_application,
        },
    )




# ===============================================
# INSTRUCTOR APPLICATION & PASSWORD RESET
# ===============================================

@login_required
def apply_instructor_view(request):
    """
    Halaman aplikasi menjadi instruktur
    
    Flow:
    1. Siswa isi form aplikasi (nama, headline, bio, portfolio, pengalaman, motivasi)
    2. Aplikasi di-submit & status jadi PENDING
    3. Admin review aplikasi
    4. Admin approve/reject
    5. Jika approve, user.role berubah ke 'instructor'
    
    Important: Hanya satu aplikasi PENDING diizinkan per user
    """
    if request.user.has_instructor_dashboard_access:
        messages.info(request, "Akun Anda sudah memiliki akses instructor dashboard.")
        return redirect("dashboard:index")

    pending_application = _pending_instructor_application(request.user)
    latest_application = _latest_instructor_application(request.user)

    if request.method == "POST":
        if pending_application is not None:
            messages.info(request, "Pengajuan instructor Anda masih menunggu review admin.")
            return redirect("accounts:apply_instructor")

        form = InstructorApplicationForm(request.POST)
        if form.is_valid():
            application = form.save(commit=False)
            application.user = request.user
            application.status = InstructorApplication.STATUS_PENDING
            application.save()
            messages.success(request, "Pengajuan instructor berhasil dikirim. Admin akan meninjaunya segera.")
            return redirect("accounts:apply_instructor")
    else:
        initial_data = {
            "full_name": request.user.get_full_name() or request.user.username,
        }

        # Jika aplikasi sebelumnya di-reject, pre-fill form dengan data lama
        if latest_application is not None and latest_application.status == InstructorApplication.STATUS_REJECTED:
            initial_data.update(
                {
                    "full_name": latest_application.full_name,
                    "headline": latest_application.headline,
                    "bio": latest_application.bio,
                    "portfolio_url": latest_application.portfolio_url,
                    "experience_years": latest_application.experience_years,
                    "motivation": latest_application.motivation,
                }
            )

        form = InstructorApplicationForm(initial=initial_data)

    return render(
        request,
        "accounts/apply_instructor.html",
        {
            "form": form,
            "pending_instructor_application": pending_application,
            "latest_instructor_application": latest_application,
        },
    )


def forgot_password_view(request):
    """
    Halaman forgot password - Step 1: Request OTP
    
    Flow:
    1. User isi email
    2. System cari user dengan email itu
    3. Jika ditemukan, kirim OTP
    4. User diarahkan ke verifikasi OTP
    """
    if request.user.is_authenticated:
        return redirect("courses:discovery")

    if request.method == "POST":
        form = ForgotPasswordRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"].strip().lower()
            user = _get_user_by_email(email)

            if user is not None:
                # Cek cooldown
                can_request, retry_after = can_request_new_otp(user, purpose=OTP.PURPOSE_PASSWORD_RESET)
                if not can_request:
                    messages.error(request, f"OTP request is still in cooldown. Please wait {retry_after} seconds and try again.")
                    return render(request, "accounts/forgot_password.html", {"form": form})

                # Kirim OTP
                issue_otp(user, purpose=OTP.PURPOSE_PASSWORD_RESET)
                messages.success(request, "OTP sent. Please check your inbox and spam folder.")
            else:
                # Security: Jangan expose apakah email ada atau tidak
                messages.info(request, "If the account exists, an OTP has been sent to the email address.")

            # Simpan email ke session untuk next step
            request.session["password_reset_email"] = email
            return redirect("accounts:verify_reset_otp")
    else:
        form = ForgotPasswordRequestForm()

    return render(request, "accounts/forgot_password.html", {"form": form})


def verify_reset_otp_view(request):
    """
    Halaman verifikasi OTP reset password - Step 2: Verify OTP
    
    User isi OTP code yang diterima di email
    Jika benar, session di-mark sebagai verified
    """
    if request.user.is_authenticated:
        return redirect("courses:discovery")

    email = request.session.get("password_reset_email")
    if not email:
        messages.info(request, "Start from forgot password first.")
        return redirect("accounts:forgot_password")

    if request.method == "POST":
        form = OTPVerificationForm(request.POST)
        if form.is_valid():
            user = _get_user_by_email(email)
            if user is None:
                messages.error(request, "Invalid reset session. Please request OTP again.")
                request.session.pop("password_reset_email", None)
                request.session.pop("password_reset_verified", None)
                return redirect("accounts:forgot_password")

            # Verify OTP
            otp, message, error_code = verify_user_otp(
                user,
                form.cleaned_data["otp"],
                purpose=OTP.PURPOSE_PASSWORD_RESET,
            )
            if otp is None:
                if error_code == "locked":
                    messages.error(request, "Too many wrong OTP attempts. Please request a new OTP.")
                else:
                    messages.error(request, message)
                return render(request, "accounts/verify_reset_otp.html", {"form": form, "email": email})

            # OTP verified! Mark session as verified
            request.session["password_reset_verified"] = True
            messages.success(request, "OTP verified. You can now set a new password.")
            return redirect("accounts:reset_password")
    else:
        form = OTPVerificationForm()

    return render(request, "accounts/verify_reset_otp.html", {"form": form, "email": email})


def reset_password_view(request):
    """
    Halaman reset password - Step 3: Set new password
    
    Hanya bisa diakses jika:
    1. Ada email di session (dari forgot password)
    2. OTP sudah verified (dari verify_reset_otp)
    
    User isi password baru & confirm password
    Password berhasil di-update
    """
    if request.user.is_authenticated:
        return redirect("courses:discovery")

    email = request.session.get("password_reset_email")
    is_verified = request.session.get("password_reset_verified", False)

    if not email:
        messages.info(request, "Start from forgot password first.")
        return redirect("accounts:forgot_password")

    if not is_verified:
        messages.info(request, "Verify OTP first before resetting password.")
        return redirect("accounts:verify_reset_otp")

    if request.method == "POST":
        form = ResetPasswordForm(request.POST)
        if form.is_valid():
            user = _get_user_by_email(email)
            if user is None:
                messages.error(request, "Invalid reset session. Please request OTP again.")
                request.session.pop("password_reset_email", None)
                request.session.pop("password_reset_verified", None)
                return redirect("accounts:forgot_password")

            # Get the OTP yang sudah diverifikasi
            verified_otp = get_verified_otp(user, purpose=OTP.PURPOSE_PASSWORD_RESET)
            if verified_otp is None:
                messages.error(request, "OTP session is invalid or expired. Please request OTP again.")
                request.session.pop("password_reset_email", None)
                request.session.pop("password_reset_verified", None)
                return redirect("accounts:forgot_password")

            # Update password
            user.set_password(form.cleaned_data["new_password"])
            user.save(update_fields=["password"])
            mark_otp_used(verified_otp)

            # Clear session
            request.session.pop("password_reset_email", None)
            request.session.pop("password_reset_verified", None)
            messages.success(request, "Password reset successful. Please login with your new password.")
            return redirect("accounts:login")
    else:
        form = ResetPasswordForm()

    return render(request, "accounts/reset_password.html", {"form": form, "email": email})


# =============== HELPER FUNCTIONS ===============
def _get_user_by_email(email):
    """Case-insensitive email lookup"""
    return User.objects.filter(email__iexact=email.strip()).first()


def _build_token_response(user):
    """Build JWT token response untuk API"""
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}




# ===============================================
# REST API ENDPOINTS (For Mobile App / Frontend Framework)
# ===============================================
# API endpoints untuk authentication
# Return JSON response (bukan HTML like web views)
# Semua endpoint return JWT tokens untuk subsequent API calls

class LoginAPIView(APIView):
    """
    API: Login dengan email & password
    
    Endpoint: POST /api/accounts/login/
    Request: {"email": "...", "password": "..."}
    Response: {"email": "...", "detail": "OTP sent..."}
    Status: 200 atau 429 (cooldown)
    
    Next step: User verify OTP dengan LoginVerifyOTPAPIView
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]

        can_request, retry_after = can_request_new_otp(user, purpose=OTP.PURPOSE_LOGIN)
        if not can_request:
            return Response(
                {"detail": "OTP request is on cooldown.", "retry_after_seconds": retry_after},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        issue_otp(user, purpose=OTP.PURPOSE_LOGIN)
        return Response(
            {
                "detail": "OTP sent successfully. Verify OTP to complete login.",
                "email": user.email,
            },
            status=status.HTTP_200_OK,
        )


class LoginVerifyOTPAPIView(APIView):
    """
    API: Verifikasi OTP login & dapatkan JWT tokens
    
    Endpoint: POST /api/accounts/login/verify-otp/
    Request: {"email": "...", "otp": "123456"}
    Response: {"user": {...}, "access": "...", "refresh": "...", "detail": "Login successful."}
    Status: 200, 400, atau 429 (too many attempts)
    
    Access token digunakan untuk API calls berikutnya:
    Header: Authorization: Bearer {access_token}
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginOTPVerifySerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]

        otp, message, error_code = verify_user_otp(
            user,
            serializer.validated_data["otp"],
            purpose=OTP.PURPOSE_LOGIN,
        )
        if otp is None:
            response_status = status.HTTP_429_TOO_MANY_REQUESTS if error_code == "locked" else status.HTTP_400_BAD_REQUEST
            return Response({"detail": message}, status=response_status)

        mark_otp_used(otp)
        token_data = _build_token_response(user)
        return Response(
            {"detail": "Login successful.", "user": UserSerializer(user).data, **token_data},
            status=status.HTTP_200_OK,
        )


class ForgotPasswordAPIView(APIView):
    """
    API: Forgot password - Step 1: Request OTP
    
    Endpoint: POST /api/accounts/forgot-password/
    Request: {"email": "..."}
    Response: {"detail": "If the account exists, an OTP has been sent."}
    Status: 200 atau 429 (cooldown)
    
    Security: Response sama whether email exists or not (prevent email enumeration)
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = _get_user_by_email(serializer.validated_data["email"])

        if user is None:
            return Response({"detail": "If the account exists, an OTP has been sent."}, status=status.HTTP_200_OK)

        can_request, retry_after = can_request_new_otp(user, purpose=OTP.PURPOSE_PASSWORD_RESET)
        if not can_request:
            return Response(
                {"detail": "OTP request is on cooldown.", "retry_after_seconds": retry_after},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        issue_otp(user, purpose=OTP.PURPOSE_PASSWORD_RESET)
        return Response({"detail": "OTP sent successfully."}, status=status.HTTP_200_OK)


class ResendOTPAPIView(APIView):
    """
    API: Resend OTP (untuk forgot password atau login)
    
    Endpoint: POST /api/accounts/resend-otp/
    Request: {"email": "..."}
    Response: {"detail": "OTP resent successfully."}
    Status: 200 atau 429 (cooldown)
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = _get_user_by_email(serializer.validated_data["email"])

        if user is None:
            return Response({"detail": "If the account exists, an OTP has been sent."}, status=status.HTTP_200_OK)

        can_request, retry_after = can_request_new_otp(user, purpose=OTP.PURPOSE_PASSWORD_RESET)
        if not can_request:
            return Response(
                {"detail": "OTP request is on cooldown.", "retry_after_seconds": retry_after},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        issue_otp(user, purpose=OTP.PURPOSE_PASSWORD_RESET)
        return Response({"detail": "OTP resent successfully."}, status=status.HTTP_200_OK)


class VerifyOTPAPIView(APIView):
    """
    API: Verifikasi OTP (untuk forgot password flow)
    
    Endpoint: POST /api/accounts/verify-otp/
    Request: {"email": "...", "otp": "123456"}
    Response: {"detail": "OTP verified successfully."}
    Status: 200 atau 400 (invalid OTP)
    
    Next step: Reset password dengan ResetPasswordAPIView
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = _get_user_by_email(serializer.validated_data["email"])

        if user is None:
            return Response({"detail": "Invalid email or OTP."}, status=status.HTTP_400_BAD_REQUEST)

        otp, message, error_code = verify_user_otp(
            user,
            serializer.validated_data["otp"],
            purpose=OTP.PURPOSE_PASSWORD_RESET,
        )
        if otp is None:
            response_status = status.HTTP_429_TOO_MANY_REQUESTS if error_code == "locked" else status.HTTP_400_BAD_REQUEST
            return Response({"detail": message}, status=response_status)

        return Response({"detail": message}, status=status.HTTP_200_OK)


class ResetPasswordAPIView(APIView):
    """
    API: Reset password - Step 3 (after OTP verified)
    
    Endpoint: POST /api/accounts/reset-password/
    Request: {"email": "...", "new_password": "..."}
    Response: {"detail": "Password reset successfully."}
    Status: 200 atau 400 (invalid session)
    
    Prerequisite: User harus sudah verify OTP dengan VerifyOTPAPIView
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = _get_user_by_email(serializer.validated_data["email"])

        if user is None:
            return Response({"detail": "Invalid request."}, status=status.HTTP_400_BAD_REQUEST)

        verified_otp = get_verified_otp(user, purpose=OTP.PURPOSE_PASSWORD_RESET)
        if verified_otp is None:
            return Response(
                {"detail": "OTP verification is required before resetting the password."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        mark_otp_used(verified_otp)

        return Response({"detail": "Password reset successfully."}, status=status.HTTP_200_OK)
