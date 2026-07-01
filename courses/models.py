import re
import uuid
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.db import models
from django.db.models import Avg
from django.utils import timezone
from django.core.exceptions import ValidationError


# ===============================================
# MODEL: Course (Kursus)
# ===============================================
# Menyimpan semua informasi kursus yang dibuat oleh instruktur
# Field penting:
# - instructor: siapa pembuat kursus (ForeignKey ke User)
# - title, description: judul & deskripsi kursus
# - price: harga kursus (0 = gratis, >0 = berbayar)
# - youtube_url: video trailer/pengenalan kursus
# - thumbnail: gambar cover kursus
class Course(models.Model):
    # Instruktur pembuat kursus
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="courses",
    )
    # Judul kursus
    title = models.CharField(max_length=200)
    # Deskripsi detail kursus
    description = models.TextField()
    # Harga kursus (0 = gratis, >0 = berbayar)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # URL video YouTube untuk trailer/preview kursus
    youtube_url = models.URLField(blank=True)
    
    def _thumbnail_upload_to(instance, filename):
        ext = filename.split(".")[-1].lower()
        return f"courses/thumbnails/{uuid.uuid4().hex}.{ext}"

    # Gambar cover/thumbnail kursus (disimpan di media/courses/thumbnails/)
    thumbnail = models.ImageField(upload_to=_thumbnail_upload_to, blank=True, null=True)
    # Waktu kursus dibuat
    created_at = models.DateTimeField(auto_now_add=True)
    # Waktu kursus terakhir diupdate
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    # ✓ Hitung total siswa yang sudah enroll ke kursus ini
    @property
    def enrolled_students_count(self):
        return self.enrollments.count()

    # ✓ Cek apakah kursus berbayar atau gratis
    @property
    def is_paid(self):
        return self.price > 0

    # ✓ Hitung rating rata-rata dari semua review
    @property
    def average_rating(self):
        return round(self.reviews.aggregate(avg=Avg("rating"))["avg"] or 0.0, 1)

    # ✓ Hitung jumlah review/rating untuk kursus ini
    @property
    def review_count(self):
        return self.reviews.count()

    # ✓ Convert YouTube URL ke embed URL yang bisa dimainkan di HTML
    # Contoh: https://youtu.be/abc123 → https://www.youtube-nocookie.com/embed/abc123
    @property
    def youtube_embed_url(self):
        if not self.youtube_url:
            return ""

        # Parse URL untuk extract video ID
        parsed = urlparse(self.youtube_url)
        video_id = ""

        # Handle youtu.be short URL
        if "youtu.be" in parsed.netloc.lower():
            video_id = parsed.path.strip("/").split("?")[0]
        # Handle youtube.com URL
        elif "youtube.com" in parsed.netloc.lower():
            if parsed.path == "/watch":
                video_id = parse_qs(parsed.query).get("v", [""])[0]
            else:
                # Handle embed, shorts, live URLs
                match = re.search(r"/(?:embed|shorts|live)/([A-Za-z0-9_-]+)", parsed.path)
                if match:
                    video_id = match.group(1)

        if not video_id:
            return ""

        # Return embed URL dengan privacy mode (youtube-nocookie.com)
        return (
            f"https://www.youtube-nocookie.com/embed/{video_id}"
            "?rel=0&modestbranding=1&iv_load_policy=3&playsinline=1"
        )

    def save(self, *args, **kwargs):
        # Validate thumbnail content and size before saving to prevent malicious uploads
        if self.thumbnail:
            MAX_THUMBNAIL_SIZE = 2 * 1024 * 1024  # 2 MB
            MAX_DIMENSION = 2000
            ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP")
            try:
                from PIL import Image, UnidentifiedImageError

                try:
                    size = getattr(self.thumbnail, "size", 0)
                    if size and size > MAX_THUMBNAIL_SIZE:
                        raise ValidationError("Thumbnail terlalu besar (maks 2MB).")

                    # Verify image
                    self.thumbnail.seek(0)
                    img = Image.open(self.thumbnail)
                    img.verify()
                    fmt = getattr(img, "format", None)
                    if fmt and fmt.upper() not in ALLOWED_FORMATS:
                        raise ValidationError("Format gambar tidak didukung (JPEG, PNG, WEBP).")

                    # Re-open to check dimensions (verify() may close file)
                    self.thumbnail.seek(0)
                    img = Image.open(self.thumbnail)
                    w, h = img.size
                    if w > MAX_DIMENSION or h > MAX_DIMENSION:
                        raise ValidationError(f"Dimensi gambar terlalu besar (maks {MAX_DIMENSION}px).")
                finally:
                    try:
                        self.thumbnail.seek(0)
                    except Exception:
                        pass
            except ImportError:
                raise ValidationError("Server tidak memiliki dependensi gambar (Pillow).")
            except UnidentifiedImageError:
                raise ValidationError("File yang diunggah bukan gambar yang valid.")

        super().save(*args, **kwargs)

    def is_redeemable(self):
        return self.is_active and (not self.is_expired) and (not self.is_used)


# ===============================================
# MODEL: CourseDiscussion (Diskusi Kursus)
# ===============================================
# Menyimpan diskusi/pertanyaan siswa di kursus
# Siswa bisa bertanya, instructor/siswa lain bisa jawab
class CourseDiscussion(models.Model):
    # Kursus yang didiskusikan
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="discussions",
    )
    # User yang membuat diskusi
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="course_discussions",
    )
    # Pesan/pertanyaan dari user
    message = models.TextField()
    # Waktu diskusi dibuat
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Urutkan dari diskusi tertua ke terbaru
        ordering = ["created_at"]

    def __str__(self):
        return f"Discussion by {self.user} on {self.course}"


# ===============================================
# MODEL: CourseReview (Review/Rating Kursus)
# ===============================================
# Menyimpan review & rating dari siswa yang sudah selesai/mengambil kursus
class CourseReview(models.Model):
    # Pilihan rating 1-5 bintang
    RATING_CHOICES = [
        (1, "1 star"),
        (2, "2 stars"),
        (3, "3 stars"),
        (4, "4 stars"),
        (5, "5 stars"),
    ]

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="course_reviews",
    )
    rating = models.PositiveSmallIntegerField(choices=RATING_CHOICES, default=5)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("course", "user")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Review {self.rating} for {self.course} by {self.user}"


class CartPayment(models.Model):
    STATUS_PENDING = "pending"
    STATUS_SETTLEMENT = "settlement"
    STATUS_CAPTURE = "capture"
    STATUS_DENY = "deny"
    STATUS_EXPIRE = "expire"
    STATUS_CANCEL = "cancel"
    STATUS_ERROR = "error"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SETTLEMENT, "Settlement"),
        (STATUS_CAPTURE, "Capture"),
        (STATUS_DENY, "Deny"),
        (STATUS_EXPIRE, "Expire"),
        (STATUS_CANCEL, "Cancel"),
        (STATUS_ERROR, "Error"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cart_payments",
    )
    order_id = models.CharField(max_length=80, unique=True)
    course_ids = models.JSONField(default=list, blank=True)
    gross_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    snap_token = models.CharField(max_length=255, blank=True)
    transaction_id = models.CharField(max_length=100, blank=True)
    payment_type = models.CharField(max_length=50, blank=True)
    raw_response = models.JSONField(default=dict, blank=True, null=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.order_id} - {self.user.username}"
