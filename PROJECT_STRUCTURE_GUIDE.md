# SkillForge Project - Panduan Struktur Code untuk Presentasi

## 📋 Ringkasan File-File Penting

Semua file Python sudah dilengkapi dengan **komentar lengkap** (hashtag #) untuk menjelaskan fungsinya. Berikut adalah penjelasan singkat:

---

## 🏗️ STRUKTUR FOLDER & FUNGSI

### **1. accounts/ - Autentikasi & Profil User**

| File | Fungsi |
|------|--------|
| [accounts/models.py](accounts/models.py) | **User model** (role: student/instructor), **InstructorApplication** (aplikasi jadi guru), **OTP** (One-Time Password via email) |
| [accounts/views.py](accounts/views.py) | **Register**, **Login via OTP**, **Forgot Password**, **Edit Profil**, **Ganti Password**, **Apply Instructor**, **REST API endpoints** |
| accounts/urls.py | Routing untuk semua auth endpoints |
| accounts/forms.py | Form validation (register, login, profil, aplikasi instruktur) |
| accounts/serializers.py | JSON serializers untuk REST API |
| accounts/utils.py | Helper functions (OTP generation, verification, rate limiting) |
| accounts/auth_backends.py | Custom authentication backends |

---

### **2. courses/ - Manajemen Kursus**

| File | Fungsi |
|------|--------|
| [courses/models.py](courses/models.py) | **Course** (kursus), **CourseDiscussion** (Q&A), **CourseReview** (rating), **CartPayment** (checkout) |
| [courses/views.py](courses/views.py) | **Browse courses**, **Course detail**, **Add to cart**, **Checkout (Midtrans)**, **Instructor dashboard**, **Admin dashboard**, **Payment webhook** |
| courses/urls.py & dashboard_urls.py | Routing untuk courses & dashboard |
| courses/forms.py | Form untuk edit kursus, review, withdrawal |
| courses/context_processors.py | Template context helpers |

---

### **3. enrollments/ - Pendaftaran & Revenue**

| File | Fungsi |
|------|--------|
| [enrollments/models.py](enrollments/models.py) | **Enrollment** (siswa daftar kursus), **Invoice** (struk pembayaran), **RevenueLedger** (accounting revenue), **InstructorWithdraw** (pencairan dana) |

---

### **4. api/ - REST API Backend**

| File | Fungsi |
|------|--------|
| api/views.py | API endpoints (courses, enrollments, payments) |
| api/serializers.py | JSON serializers |
| api/urls.py | API routing |
| api/permissions.py | Custom permission classes |

---

### **5. skillforge/ - Main Config**

| File | Fungsi |
|------|--------|
| [skillforge/settings.py](skillforge/settings.py) | Django configuration (database, installed apps, middleware, security) |
| [skillforge/urls.py](skillforge/urls.py) | **Main URL router** (semua paths) |
| skillforge/wsgi.py | WSGI entry point untuk production |

---

## 🔄 FLOW UTAMA APLIKASI

### **1. REGISTRATION & LOGIN**
```
User → Register Form → Create User → Auto Login → Discovery Page
User → Login Form (Email) → OTP sent → Verify OTP → Login → Discovery
```

### **2. BROWSE & BUY COURSES**
```
Discovery Page → Course Detail → Add to Cart → Checkout → Midtrans Payment
→ Payment Success → Create Enrollment → Access Course
```

### **3. BECOME INSTRUCTOR**
```
Student → Apply Instructor Form → Submit Application (PENDING)
→ Admin Review → Approve/Reject
→ If Approve: User.role = "instructor"
→ Instructor Dashboard Access
```

### **4. INSTRUCTOR DASHBOARD**
```
Create Course → Upload Thumbnail & Video → Set Price → Publish
→ Students Buy Course → Revenue Generated → Withdraw Request
→ Admin Review & Approve → Dana ditransfer
```

### **5. PAYMENT FLOW (Midtrans)**
```
Checkout → Build Midtrans Snap URL → User Pay
→ Midtrans Notification (Webhook) → Update CartPayment Status
→ Create Enrollment → Create RevenueLedger (for accounting)
```

---

## 🔐 AUTHENTICATION SYSTEM

**Bukan password biasa, tapi OTP (One-Time Password) via Email!**

- **Login**: Email + Password → OTP sent to email → Verify OTP → JWT Token
- **Password Reset**: Forgot → OTP sent → Verify OTP → Set new password
- **Change Password**: Verify current password → OTP sent → Verify OTP → Update
- **Instructor Apply**: No OTP, just submit form → Admin review

---

## 📊 DATABASE MODELS (Relationships)

```
User (1) ──→ (∞) Enrollment (∞) ← Course (1)
     ↓
     └──→ InstructorApplication
     └──→ OTP (multiple)
     └──→ CartPayment
     └──→ RevenueLedger (as instructor)
     └──→ InstructorWithdraw

Course (1) ──→ (∞) CourseDiscussion
         ──→ (∞) CourseReview
         ──→ (∞) Enrollment
```

---

## 🛡️ SECURITY FEATURES

✅ **OTP Rate Limiting** - Cooldown setelah request OTP (prevent brute force)
✅ **OTP Expiration** - OTP expired setelah 10 menit
✅ **Session Security** - CSRF protection, secure cookies
✅ **Password Hashing** - Use Django's hashing (not plaintext)
✅ **JWT Tokens** - For REST API authentication
✅ **Role-Based Access Control** - Student/Instructor/Admin roles
✅ **Permission Checks** - Every action verified

---

## 🔑 KEY FUNCTIONS & CONCEPTS

### **accounts/views.py Highlights:**
- `register_view()` - Registrasi user baru
- `login_view()` - Login dengan email (step 1)
- `verify_login_otp_view()` - Verifikasi OTP login (step 2)
- `profile_view()` - Multi-action profile page (edit, change password, instructor app)
- API Classes (LoginAPIView, VerifyOTPAPIView, etc.) - JSON API endpoints

### **courses/views.py Highlights:**
- `_has_dashboard_access()` - Check dashboard permission
- `_get_instructor_balance()` - Hitung total saldo instruktur
- `_record_revenue_ledger()` - Catat penjualan ke accounting
- `_midtrans_*()` - Midtrans payment helpers
- `home_view()` - Landing page
- `course_discovery_view()` - Browse all courses
- `cart_view()`, `checkout_view()` - Shopping cart

### **enrollments/models.py Highlights:**
- `RevenueLedger` - **CRITICAL** untuk hitung saldo instruktur
- `InstructorWithdraw` - Tracking pencairan dana
- `Invoice` - Multi-course purchase tracking

---

## 🎯 UNTUK PRESENTASI

### **Urutan Penjelasan yang Baik:**

1. **Start dengan Models** → Tunjukkan [accounts/models.py](accounts/models.py), [courses/models.py](courses/models.py), [enrollments/models.py](enrollments/models.py)
   - Jelaskan: User roles, OTP system, Course structure, Revenue tracking

2. **Flow Diagram** → Tunjukkan authentication & payment flow
   - Registration → Login (OTP) → Browse → Cart → Payment → Enrollment → Revenue

3. **Views Layer** → Tunjukkan [accounts/views.py](accounts/views.py) & [courses/views.py](courses/views.py)
   - Jelaskan: How registration works, how OTP works, how payment works

4. **URL Routing** → Tunjukkan [skillforge/urls.py](skillforge/urls.py)
   - Semua endpoint mapped dengan jelas

5. **Database** → Tunjukkan relationships di models
   - How data flows dari registrasi hingga revenue

---

## 📝 NOTES

- Semua function sudah punya **docstring** (komentar penjelasan)
- Helper functions (dengan prefix `_`) adalah internal/private functions
- Session keys digunakan untuk temporary data storage per user
- Cooldown system prevents OTP brute force attacks
- RevenueLedger adalah source of truth untuk saldo instruktur

---

**Good luck dengan presentasi! 🚀**
