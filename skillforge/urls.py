# ===============================================
# Django URL Configuration (Main Router)
# ===============================================
# File ini adalah routing utama untuk semua request masuk ke aplikasi
# URL pattern akan di-match dari atas ke bawah, request diteruskan ke handler pertama yang match

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from courses.views import home_view

# URL Patterns (daftar routes)
urlpatterns = [
    # ========== ADMIN ==========
    # Django admin panel (untuk manage data di database)
    # Akses: /admin/ → admin interface
    path("admin/", admin.site.urls),
    
    # ========== AUTHENTICATION ==========
    # OAuth & social login (Google, dll via django-allauth)
    # Akses: /oauth/ → social auth endpoints
    path("oauth/", include("allauth.urls")),
    
    # User auth (login, register, OTP, forgot password)
    # Akses: /accounts/register/, /accounts/login/, dll
    path("accounts/", include("accounts.urls")),
    
    # ========== DASHBOARD ==========
    # Dashboard untuk admin, instructor, student (role-based)
    # Akses: /dashboard/ → redirect sesuai role user
    path("dashboard/", include("courses.dashboard_urls")),
    
    # ========== COURSES (PUBLIC) ==========\n    # Halaman public untuk browse/beli kursus, cart, checkout
    # Akses: /courses/discovery/, /courses/cart/, /courses/{id}/, dll
    path("courses/", include("courses.urls")),
    
    # ========== REST API ==========
    # Backend API untuk mobile app atau frontend framework (React, Vue, dll)
    # Akses: /api/courses/, /api/enrollments/, /api/payments/, dll
    path("api/", include("api.urls")),
    
    # ========== HOME PAGE ==========
    # Halaman utama/landing page
    # Akses: / (root)
    path("", home_view, name="home"),
]

# ========== MEDIA FILES ==========
# Serve uploaded files (profile pic, course thumbnail, dll)
# Akses: /media/profiles/, /media/courses/thumbnails/, dll
# NOTE: Di production, gunakan Nginx/WhiteNoise untuk serve static & media files
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
