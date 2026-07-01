from django.conf import settings
from django.db import models


# ===============================================
# MODEL: Enrollment (Pendaftaran Siswa ke Kursus)
# ===============================================
# Menyimpan data siswa yang sudah mendaftar/enroll ke kursus
# Hubungan many-to-many antara User (siswa) & Course (kursus)
# dengan info tambahan: cara enroll (beli/redeem/gratis) & jumlah bayar
class Enrollment(models.Model):
    # Cara siswa mendapatkan akses ke kursus
    METHOD_PURCHASE = "purchase"  # Membeli dengan uang
    METHOD_REDEEM = "redeem"      # Menggunakan redeem code
    METHOD_FREE = "free"          # Akses gratis
    METHOD_CHOICES = [
        (METHOD_PURCHASE, "Purchase"),
        (METHOD_REDEEM, "Redeem"),
        (METHOD_FREE, "Free Access"),
    ]

    # Siswa yang mendaftar
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    # Kursus yang didaftari
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    # Cara siswa dapat akses (purchase/redeem/free)
    granted_via = models.CharField(max_length=20, choices=METHOD_CHOICES)
    # Jumlah uang yang dibayar (jika purchase)
    amount_paid = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    # Waktu siswa mendaftar
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "course")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} -> {self.course.title}"


# ===============================================
# MODEL: Invoice (Faktur Pembayaran)
# ===============================================
# Menyimpan invoice/struk pembayaran ketika siswa beli kursus
# Satu invoice bisa berisi banyak kursus (multi-course purchase)
class Invoice(models.Model):
    # Siswa yang membeli
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="invoices",
    )
    # Nomor invoice unik (untuk identifikasi transaksi)
    invoice_number = models.CharField(max_length=100, unique=True)
    # Daftar kursus yang dibeli dalam satu transaksi
    courses = models.ManyToManyField("courses.Course", related_name="invoices")
    # Total jumlah pembayaran
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    # Metode pembayaran (Midtrans, direct, dll)
    payment_method = models.CharField(max_length=50, default="Direct")
    # Status pembayaran (Paid, Pending, Failed)
    status = models.CharField(max_length=20, default="Paid")
    # Waktu invoice dibuat
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.invoice_number} - {self.user.username}"


# ===============================================
# MODEL: RevenueLedger (Catatan Revenue/Pendapatan)
# ===============================================
# Menyimpan setiap transaksi penjualan kursus (untuk accounting)
# PENTING: Ini adalah sumber data untuk perhitungan saldo instruktur!
# Setiap kali siswa membeli kursus, satu record RevenueLedger dibuat
class RevenueLedger(models.Model):
    # Status pembayaran dari payment gateway
    STATUS_CHOICES = [
        ("settlement", "Settlement"),  # Pembayaran sudah final
        ("capture", "Capture"),        # Pembayaran tertunda/pending
    ]

    # Pembayaran yang terkait (dari CartPayment)
    payment = models.ForeignKey(
        "courses.CartPayment",
        on_delete=models.CASCADE,
        related_name="revenue_ledger_entries",
    )
    # Siswa yang melakukan pembelian
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="revenue_ledger_entries",
    )
    # Kursus yang dibeli
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.CASCADE,
        related_name="revenue_ledger_entries",
    )
    # Instruktur pemilik kursus (penerima revenue)
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="instructor_revenue_ledger_entries",
        null=True,
        blank=True,
    )
    # Jumlah bruto yang dihasilkan
    gross_amount = models.DecimalField(max_digits=10, decimal_places=2)
    # Status pembayaran (settlement/capture)
    payment_status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    # Tipe pembayaran (credit_card, e_wallet, bank_transfer, dll)
    payment_type = models.CharField(max_length=50, blank=True)
    # Waktu pembayaran berhasil
    paid_at = models.DateTimeField(blank=True, null=True)
    # Waktu record dibuat
    created_at = models.DateTimeField(auto_now_add=True)
    # Waktu record terakhir update
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-paid_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["payment", "course"], name="unique_revenue_ledger_per_payment_course")
        ]

    def __str__(self):
        return f"{self.payment.order_id} - {self.course.title} - {self.gross_amount}"


# ===============================================
# MODEL: InstructorWithdraw (Pengajuan Pencairan Dana)
# ===============================================
# Menyimpan pengajuan withdrawal/pencairan dana dari instruktur
# Flow: Instruktur ajukan → Admin review → Admin approve → Dana ditransfer
class InstructorWithdraw(models.Model):
    # Status withdrawal
    STATUS_PENDING = "pending"    # Menunggu review admin
    STATUS_PAID = "paid"          # Sudah di-approve & dana ditransfer
    STATUS_REJECTED = "rejected"  # Ditolak oleh admin

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PAID, "Paid"),
        (STATUS_REJECTED, "Rejected"),
    ]

    # Instruktur yang mengajukan withdrawal
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="withdraw_requests",
    )
    # Jumlah dana yang ingin dicairkan
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    # Snapshot saldo total instruktur saat mengajukan (untuk audit trail)
    balance_snapshot = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Detail bank untuk transfer
    bank_name = models.CharField(max_length=100)  # Nama bank (BCA, Mandiri, dll)
    account_name = models.CharField(max_length=150)  # Nama pemilik rekening
    account_number = models.CharField(max_length=100)  # Nomor rekening
    # Catatan tambahan dari instruktur
    note = models.TextField(blank=True)
    # Status withdrawal (pending/paid/rejected)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    # Catatan review dari admin (alasan approve/reject)
    review_note = models.TextField(blank=True)
    # Admin yang me-review withdrawal ini
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_withdraw_requests",
        blank=True,
        null=True,
    )
    # Waktu admin me-review
    reviewed_at = models.DateTimeField(blank=True, null=True)
    # Waktu dana berhasil ditransfer
    paid_at = models.DateTimeField(blank=True, null=True)
    # Waktu pengajuan dibuat
    created_at = models.DateTimeField(auto_now_add=True)
    # Waktu terakhir diupdate
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Withdraw({self.instructor_id}, {self.amount}, {self.status})"

