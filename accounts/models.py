from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.utils import timezone


# ===============================================
# MODEL: InstructorApplication
# ===============================================
# Menyimpan aplikasi siswa yang ingin menjadi instruktur
# Admin harus approve aplikasi ini agar siswa bisa membuat kursus
# Status: pending (menunggu review), approved (diterima), rejected (ditolak)
class InstructorApplication(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="instructor_applications",
    )
    full_name = models.CharField(max_length=150)
    headline = models.CharField(max_length=200)
    bio = models.TextField()
    portfolio_url = models.URLField(blank=True)
    experience_years = models.PositiveSmallIntegerField(default=0)
    motivation = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    review_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_instructor_applications",
        blank=True,
        null=True,
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(status="pending"),
                name="unique_pending_instructor_application_per_user",
            )
        ]

    def __str__(self):
        return f"InstructorApplication({self.user_id}, {self.status})"


# ===============================================
# MODEL: User (Custom User Model)
# ===============================================
# Extends Django's AbstractUser dengan field tambahan:
# - profile_image: foto profil user
# - bio: deskripsi singkat user
# - role: menentukan akses user (student atau instructor)
#
# Penting: role digunakan untuk role-based access control
# - student: hanya bisa browse & beli kursus
# - instructor: bisa membuat & manage kursus
class User(AbstractUser):
    ROLE_STUDENT = "student"
    ROLE_INSTRUCTOR = "instructor"
    ROLE_CHOICES = [
        (ROLE_STUDENT, "Student"),
        (ROLE_INSTRUCTOR, "Instructor"),
    ]

    # Foto profil user (disimpan di folder media/profiles/)
    profile_image = models.ImageField(upload_to="profiles/", blank=True, null=True)
    # Bio/deskripsi singkat user (max 100 karakter)
    bio = models.CharField(max_length=100, blank=True, default="")
    # Role user yang menentukan permission & akses dashboard
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_STUDENT, db_index=True)

    class Meta(AbstractUser.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["email"],
                condition=~Q(email=""),
                name="unique_nonempty_user_email",
            )
        ]

    # ✓ Helper property: cek apakah user adalah instructor
    @property
    def is_instructor(self):
        return self.role == self.ROLE_INSTRUCTOR

    # ✓ Helper property: cek apakah user bisa akses instructor dashboard
    # (staff, superuser, atau sudah di-approve jadi instructor)
    @property
    def has_instructor_dashboard_access(self):
        return self.is_staff or self.is_superuser or self.is_instructor


# ===============================================
# MODEL: OTP (One Time Password)
# ===============================================
# Menyimpan OTP yang dikirim ke email user untuk verifikasi
# Digunakan untuk login & reset password
class OTP(models.Model):
    # Purpose OTP: login atau password reset
    PURPOSE_LOGIN = "login"
    PURPOSE_PASSWORD_RESET = "password_reset"
    PURPOSE_CHOICES = [
        (PURPOSE_LOGIN, "Login"),
        (PURPOSE_PASSWORD_RESET, "Password Reset"),
    ]

    # Relasi ke user yang menerima OTP
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="otps")
    # Tujuan penggunaan OTP ini
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES, default=PURPOSE_PASSWORD_RESET)
    # Kode OTP (random 6-8 digit, disimpan hashed)
    otp_code = models.CharField(max_length=128)
    # Waktu OTP dibuat
    created_at = models.DateTimeField(auto_now_add=True)
    # Status: sudah diverifikasi atau belum
    is_verified = models.BooleanField(default=False)
    # Waktu OTP expired (biasanya 10 menit dari created_at)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "purpose", "is_used", "is_verified", "expires_at"]),
        ]

    def __str__(self):
        return f"OTP(user={self.user_id}, verified={self.is_verified}, used={self.is_used})"

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at
