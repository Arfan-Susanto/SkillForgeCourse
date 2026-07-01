# SkillForge SaaS MVP (Django + DRF + Tailwind)

A learning platform MVP with two access levels:
- Staff: manage courses and the Django admin dashboard
- User: browse discovery page, purchase courses (dummy), redeem codes, access enrolled courses
- API: auth, courses CRUD, enrollment purchase, redeem flow

## Tech Stack
- Django
- Django REST Framework
- SQLite3 (development)
- Django Templates
- Tailwind CSS (CDN)
- Optional semantic retrieval with Qdrant + sentence-transformers

## Project Structure
- accounts/
- courses/
- enrollments/
- api/
- templates/
- static/
- manage.py

## Setup
1. Create and activate a virtual environment.
2. Install dependencies:
   - pip install -r requirements.txt
3. Run migrations:
   - python manage.py makemigrations
   - python manage.py migrate
4. Create admin user (optional):
   - python manage.py createsuperuser
5. Start server:
   - python manage.py runserver

## Production Deploy Static Files
Kalau browser menampilkan error seperti `Refused to apply style ... MIME type (text/html)` atau admin Django jadi polos di VPS, artinya URL `/static/...` sedang dibalas HTML error page, biasanya 404 dari Nginx atau proxy. Jadi masalahnya bukan CSS rusak, tapi static file tidak disajikan dengan benar.

Jalankan ini setelah deploy ke production:

```bash
python manage.py collectstatic --noinput
```

Pastikan juga:
- `DEBUG=False`
- `STATIC_ROOT` mengarah ke folder yang benar, sekarang: `staticfiles/`
- Aplikasi dijalankan lewat Gunicorn/WSGI, bukan `runserver`

Kalau kamu pakai Nginx, pakai config seperti ini:

```nginx
location /static/ {
   alias /home/DzulFahmi/skillforgecourrse/staticfiles/;
}

location /media/ {
   alias /home/DzulFahmi/skillforgecourrse/media/;
}

location / {
   proxy_pass http://127.0.0.1:8000;
   proxy_set_header Host $host;
   proxy_set_header X-Real-IP $remote_addr;
   proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
   proxy_set_header X-Forwarded-Proto $scheme;
}
```

Kalau tidak pakai Nginx, WhiteNoise di Django akan melayani `/static/` langsung dari `staticfiles/`.

## OTP Email Delivery Setup
By default, this project uses console email backend in `DEBUG` so local development does not depend on Gmail.
That means OTP emails are printed to terminal and not sent to inbox unless you explicitly enable SMTP.

Recommended setup: create a local `.env` file in the project root and put SMTP values there. The project will load it automatically on startup.

To send real emails (for example Gmail SMTP), set environment variables before running the server:

Windows PowerShell example:
- $env:EMAIL_HOST="smtp.gmail.com"
- $env:EMAIL_PORT="587"
- $env:EMAIL_HOST_USER="your_email@gmail.com"
- $env:EMAIL_HOST_PASSWORD="your_app_password"
- $env:EMAIL_USE_TLS="true"
- $env:DEFAULT_FROM_EMAIL="SkillForge <your_email@gmail.com>"

Optional overrides:
- $env:DJANGO_EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend"
- $env:EMAIL_TIMEOUT="20"

If you want to use Gmail SMTP in local development, set `DJANGO_EMAIL_BACKEND` to SMTP and make sure you use a valid Google App Password.

Important for Gmail:
- Enable 2-Step Verification.
- Generate a 16-character App Password from Google Account Security.
- Use that App Password in EMAIL_HOST_PASSWORD, not your normal Gmail password.

Example `.env` file:
```env
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=skillforgebot@gmail.com
EMAIL_HOST_PASSWORD=your_app_password
EMAIL_USE_TLS=true
DEFAULT_FROM_EMAIL=SkillForge <skillforgebot@gmail.com>
```

## Google Login Setup
Google login is implemented using django-allauth and available via buttons on login/register pages.

1. Create OAuth credentials in Google Cloud Console.
2. Add authorized redirect URI:
   - http://127.0.0.1:8000/oauth/google/login/callback/
3. Put credentials in `.env`:

```env
GOOGLE_OAUTH_CLIENT_ID=your_google_client_id
GOOGLE_OAUTH_CLIENT_SECRET=your_google_client_secret
```

4. Restart server after updating `.env`.

## Midtrans Sandbox Payment Setup
Checkout di halaman cart sudah bisa memakai Midtrans Snap sandbox.

1. Tambahkan env berikut ke `.env`:

```env
MIDTRANS_SERVER_KEY=your_midtrans_sandbox_server_key
MIDTRANS_CLIENT_KEY=your_midtrans_sandbox_client_key
MIDTRANS_IS_PRODUCTION=false
MIDTRANS_NOTIFICATION_URL=https://your-public-domain.example.com/courses/payment/midtrans/notification/
```

2. Restart server setelah update `.env`.

3. Buka halaman cart di:

```text
http://127.0.0.1:8000/courses/dashboard/cart/
```

Kalau kamu membuka aplikasi lewat ngrok, pastikan domain ngrok juga masuk ke `DJANGO_ALLOWED_HOSTS` dan `DJANGO_CSRF_TRUSTED_ORIGINS`. Untuk deployment produksi ini, host yang dipakai adalah:

```env
DJANGO_ALLOWED_HOSTS=103.175.219.240,skillforge.id,www.skillforge.id
```

Contoh untuk ngrok:

```env
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,.ngrok-free.app,.ngrok.app
DJANGO_CSRF_TRUSTED_ORIGINS=https://*.ngrok-free.app,https://*.ngrok.app
DJANGO_USE_X_FORWARDED_HOST=true
```

Catatan:
- `MIDTRANS_SERVER_KEY` dipakai backend untuk membuat token Snap dan memverifikasi notifikasi.
- `MIDTRANS_CLIENT_KEY` dipakai frontend untuk memuat Snap JS.
- `MIDTRANS_NOTIFICATION_URL` harus URL yang bisa diakses Midtrans dari internet. Kalau Anda masih pakai localhost, gunakan tunnel seperti ngrok lalu isi URL publiknya di sini.
- Jika `MIDTRANS_IS_PRODUCTION=true`, aplikasi akan memakai endpoint produksi Midtrans.

Contoh lokal dengan ngrok:

```text
https://xxxxxx.ngrok-free.app/courses/payment/midtrans/notification/
```

Kalau `notification_url` tidak diisi, Midtrans akan memakai konfigurasi default dari dashboard sandbox akun Anda.

## Web URLs
- Discovery: /
- Register: /accounts/register/
- Login: /accounts/login/
- Staff dashboard: /admin/
- Student dashboard: /dashboard/student/
- Redeem page: /redeem/
- Admin: /admin/

## API URLs
Base path: /api/

Auth:
- POST /api/auth/register/
- POST /api/auth/login/
- POST /api/auth/logout/
- GET /api/auth/me/

Courses:
- GET /api/courses/
- GET /api/courses/{id}/
- POST /api/courses/ (Staff only)
- PUT/PATCH /api/courses/{id}/ (Staff only)
- DELETE /api/courses/{id}/ (Staff only)

Enrollments:
- GET /api/enrollments/
- POST /api/enrollments/purchase/ with {"course_id": 1}

Redeem:
- POST /api/redeem/ with {"code": "ABC123"}

Support RAG Chat (Botcahx / DeepSeek / Gemini):
- POST /api/support/chat/ with {"message": "..."}
- GET /api/support/knowledge/ (authenticated)
- POST /api/support/knowledge/ (staff only)
- PUT/PATCH/DELETE /api/support/knowledge/{id}/ (staff only)

## AI RAG Customer Service Setup
1. Tambahkan API key provider yang ingin dipakai ke file `.env` project root:

```env
# Botcahx
BOTCAHX_API_URL=https://api.botcahx.eu.org/api/search/gpt
BOTCAHX_API_KEY=your_botcahx_api_key
BOTCAHX_TIMEOUT_SECONDS=120

# Gemini
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash-lite
GEMINI_API_URL=https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
GEMINI_TEMPERATURE=0.7
GEMINI_TOP_P=0.95
GEMINI_TOP_K=64
GEMINI_MAX_OUTPUT_TOKENS=256
GEMINI_TIMEOUT_SECONDS=60

# DeepSeek
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_API_URL=https://api.deepseek.com/chat/completions
DEEPSEEK_TEMPERATURE=0.7
DEEPSEEK_TOP_P=0.95
DEEPSEEK_MAX_TOKENS=256
```

Jika `BOTCAHX_API_KEY` diisi, support chat akan otomatis memakai Botcahx. Kalau tidak, aplikasi akan fallback ke DeepSeek lalu Gemini.
Kalau Anda ingin memaksa provider tertentu, set `SUPPORT_AI_PROVIDER=botcahx`, `deepseek`, atau biarkan kosong untuk auto-detect.
Jika jawaban AI sering terlalu lama lalu jatuh ke pesan error frontend, naikkan timeout yang dipakai provider tersebut, misalnya `GEMINI_TIMEOUT_SECONDS`.

2. Jalankan migrasi terbaru:
    - python manage.py migrate

3. Buat knowledge base (pakai user staff + token auth):

```bash
curl -X POST http://127.0.0.1:8000/api/support/knowledge/ \\
   -H "Authorization: Token YOUR_STAFF_TOKEN" \\
   -H "Content-Type: application/json" \\
   -d '{
      "title": "Kebijakan Refund",
      "content": "Refund bisa diajukan maksimal 7 hari setelah pembelian jika progress kursus di bawah 20%.",
      "source_url": "https://skillforge.id/help/refund"
   }'
```

4. Tanya ke chatbot customer service:

```bash
curl -X POST http://127.0.0.1:8000/api/support/chat/ \\
   -H "Content-Type: application/json" \\
   -d '{"message": "Bagaimana aturan refund di SkillForge?", "history": [{"role": "user", "content": "Saya baru beli kursus."}, {"role": "assistant", "content": "Silakan jelaskan kendalanya."}]}'
```

Format payload chat sekarang memakai JSON history agar turn berikutnya tetap membawa konteks percakapan sebelumnya.

Catatan implementasi:
- Retrieval menggunakan lexical scoring TF-IDF sederhana per chunk dokumen.
- Jawaban dipaksa berdasarkan konteks knowledge base.
- Jika konteks tidak cukup, model diarahkan untuk menjawab bahwa info belum tersedia.

Jika ingin cepat isi knowledge base awal tanpa input manual, jalankan:

```bash
python manage.py seed_support_kb
```

Lalu sinkronkan ke Qdrant:

```bash
python manage.py sync_support_kb_qdrant
```

## Qdrant Semantic Search Setup
Jika Anda ingin retrieval yang lebih tahan typo dan variasi kalimat, aktifkan Qdrant.

### Setup Qdrant Cloud (direkomendasikan untuk production)
1. Daftar dan buat cluster di Qdrant Cloud.
2. Salin endpoint HTTP(S) dan API key dari dashboard Qdrant Cloud.
3. Masukkan konfigurasi ini ke `.env`:

```env
SUPPORT_RAG_ENABLED=true
QDRANT_URL=https://<your-cloud-qdrant-endpoint>
QDRANT_API_KEY=<your-cloud-api-key>
QDRANT_COLLECTION=skillforge_support_kb
QDRANT_EMBEDDING_MODEL=intfloat/multilingual-e5-small
```

4. Jalankan sync support KB:

```bash
python manage.py sync_support_kb_qdrant
```

> Jika kamu menggunakan endpoint gRPC khusus, aktifkan juga:
> `QDRANT_PREFER_GRPC=true`

### Qdrant lokal hanya untuk development
Jika Anda pakai Qdrant lokal hanya di mesin development, jalankan docker-compose lokal dan set `SUPPORT_RAG_ENABLED=true` serta `QDRANT_URL=http://127.0.0.1:6333`.

```bash
docker compose -f docker-compose.qdrant.yml up -d
```

3. Tambahkan env berikut ke `.env`:

```env
SUPPORT_RAG_ENABLED=true
QDRANT_URL=http://127.0.0.1:6333
QDRANT_COLLECTION=skillforge_support_kb
QDRANT_EMBEDDING_MODEL=intfloat/multilingual-e5-small
```

4. Jalankan sync support KB:

```bash
python manage.py sync_support_kb_qdrant
```

Catatan:
- Jika `SUPPORT_RAG_ENABLED` tidak di-set atau tidak ada konfigurasi Qdrant cloud, fitur RAG akan dinonaktifkan.
- Fitur RAG cloud hanya berjalan bila `SUPPORT_RAG_ENABLED=true` dan `QDRANT_URL` telah disetel ke endpoint yang bukan localhost.
- Jika Qdrant tidak tersedia, sistem akan fallback ke retrieval lexical lama jika fitur RAG dimatikan.

## Postman Quick Test Sequence
1. Register user via API.
2. Login staff account and store token.
3. Create course as staff.
4. Register student.
5. Login student and store token.
6. Purchase course as student (or redeem code generated in UI/admin).
7. List enrollments as student.

## Notes
- Token auth is enabled for API testing in Postman.
- Session auth is available for browser UI.
- Payments can use Midtrans sandbox for the cart checkout flow.
