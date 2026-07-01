from django.core.management.base import BaseCommand

from api.models import SupportKnowledgeDocument


SEED_DOCS = [
    {
        "title": "Panduan Akses Kursus",
        "content": (
            "Setelah pembayaran atau enrollment berhasil, kursus akan muncul di menu My Courses. "
            "Jika kursus belum terlihat, pastikan status transaksi berhasil, lalu refresh halaman atau logout-login ulang. "
            "Untuk bantuan lebih lanjut, kirimkan nama kursus dan email akun Anda ke tim CS."
        ),
        "source_url": "https://skillforge.local/help/course-access",
    },
    {
        "title": "Masalah Login dan OTP",
        "content": (
            "Jika login gagal, pastikan username atau email sudah benar dan password sesuai. "
            "Untuk OTP, cek inbox email dan folder spam. Bila kode OTP kedaluwarsa, minta kirim ulang. "
            "Jika masih gagal, reset password lalu coba masuk kembali."
        ),
        "source_url": "https://skillforge.local/help/login",
    },
    {
        "title": "Kebijakan Refund",
        "content": (
            "Refund dapat diajukan jika memenuhi syarat kebijakan pembelian yang berlaku. "
            "Siapkan nomor transaksi, nama akun, nama kursus, dan alasan pengajuan saat menghubungi CS. "
            "Proses refund biasanya mengikuti verifikasi manual oleh tim support."
        ),
        "source_url": "https://skillforge.local/help/refund",
    },
    {
        "title": "Status Pembayaran",
        "content": (
            "Jika pembayaran sudah dilakukan tetapi kursus belum aktif, cek status transaksi dan bukti pembayaran. "
            "Kadang konfirmasi memerlukan waktu beberapa menit. Jika status tetap pending terlalu lama, hubungi CS dengan screenshot bukti transfer."
        ),
        "source_url": "https://skillforge.local/help/payment",
    },
    {
        "title": "Perubahan Profil Akun",
        "content": (
            "Anda bisa memperbarui nama, email, dan foto profil dari halaman Profile. "
            "Jika unggah foto gagal, pastikan file gambar valid dan ukurannya tidak terlalu besar. "
            "Untuk perubahan data sensitif, hubungi tim CS agar dibantu manual."
        ),
        "source_url": "https://skillforge.local/help/profile",
    },
    {
        "title": "Kontak Customer Service",
        "content": (
            "Jika pertanyaan Anda belum terjawab, hubungi customer service dengan menyebutkan nama akun, email, dan detail masalah. "
            "Semakin lengkap informasi yang dikirim, semakin cepat tim bisa membantu."
        ),
        "source_url": "https://skillforge.local/help/contact",
    },
]


class Command(BaseCommand):
    help = "Seed starter support knowledge base articles for SkillForge customer service."

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for index, doc in enumerate(SEED_DOCS, start=1):
            obj, created = SupportKnowledgeDocument.objects.update_or_create(
                title=doc["title"],
                defaults={
                    "content": doc["content"],
                    "source_url": doc["source_url"],
                    "is_active": True,
                    "created_by": None,
                },
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"[{index}] Created: {obj.title}"))
            else:
                updated_count += 1
                self.stdout.write(self.style.WARNING(f"[{index}] Updated: {obj.title}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed complete. Created {created_count} articles, updated {updated_count} articles."
            )
        )