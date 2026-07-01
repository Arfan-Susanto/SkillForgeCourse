import hashlib
import json
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# ===============================================
# COURSES VIEWS & BUSINESS LOGIC
# ===============================================
# File ini berisi business logic utama untuk:
# 1. Browse & detail kursus (public)
# 2. Beli kursus via cart (checkout Midtrans)
# 3. Dashboard instruktur (manage kursus, lihat revenue)
# 4. Dashboard admin (manage users, approve instructor, manage transaksi)
# 5. Payment webhook (notifikasi dari Midtrans)
#
# Helper functions bermula dengan underscore (_) adalah internal functions

from django.contrib import messages
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.cache import never_cache
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import Coalesce, ExtractMonth
from django.http import HttpResponseForbidden
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator

import requests

from accounts.models import InstructorApplication, User
from enrollments.models import Enrollment, InstructorWithdraw, Invoice, RevenueLedger

from .models import CartPayment, Course, CourseDiscussion, CourseReview
from .forms import CourseForm, CourseDiscussionForm, CourseReviewForm, InstructorWithdrawForm


# =============== SESSION KEY CONSTANTS ===============
# Key untuk menyimpan cart items di session
CART_SESSION_KEY = "course_cart"


# =============== HELPER FUNCTIONS ===============
# ✓ Check akses dashboard
def _has_dashboard_access(user):
    """Cek apakah user bisa akses dashboard (staff/superuser/instructor)"""
    return user.is_staff or user.is_superuser or getattr(user, "is_instructor", False)


# ✓ Check permission menonton video kursus
def _can_watch_course_video(user, course, enrolled=False):
    """Cek apakah user bisa menonton video kursus
    
    Diizinkan jika:
    1. User sudah enroll ke kursus (enrolled=True)
    2. User adalah instructor pemilik kursus
    3. User adalah staff/admin
    """
    if enrolled:
        return True

    if not user.is_authenticated:
        return False

    if user.is_staff or user.is_superuser:
        return True

    return course.instructor_id == user.id


# ✓ Query kursus yang bisa dikelola user
def _manageable_courses_queryset(user):
    """Ambil daftar kursus yang bisa dikelola user
    
    - Admin/Staff: bisa manage semua kursus
    - Instructor: hanya bisa manage kursus milik mereka
    - Student: tidak ada (return empty)
    """
    courses = Course.objects.select_related("instructor").order_by("-created_at")
    if user.is_staff or user.is_superuser:
        return courses
    if getattr(user, "is_instructor", False):
        return courses.filter(instructor=user)
    return courses.none()


# ✓ Ambil kursus spesifik atau 404
def _manageable_course_or_404(user, pk):
    """Ambil course dengan permission check, raise 404 jika tidak punya akses"""
    if user.is_staff or user.is_superuser:
        return get_object_or_404(Course, pk=pk)
    return get_object_or_404(Course, pk=pk, instructor=user)


# ✓ Ambil course list dari payment
def _get_payment_courses(payment):
    """Ambil daftar kursus yang dibeli dalam satu payment"""
    courses = Course.objects.filter(pk__in=payment.course_ids).select_related("instructor")
    course_map = {course.pk: course for course in courses}
    return [course_map[course_id] for course_id in payment.course_ids if course_id in course_map]


# ✓ Catat revenue ke ledger (untuk accounting instruktur)
def _record_revenue_ledger(payment):
    """Buat RevenueLedger entries saat payment berhasil
    
    Setiap course dalam payment akan membuat 1 RevenueLedger entry
    yang mencatat: course, instructor, amount, payment status
    
    PENTING: Data ini digunakan untuk hitung saldo instruktur!
    """
    if payment.status not in {CartPayment.STATUS_SETTLEMENT, CartPayment.STATUS_CAPTURE}:
        return []

    paid_at = payment.paid_at or timezone.now()
    ledger_entries = []

    for course in _get_payment_courses(payment):
        if course.instructor is None:
            continue

        # Create or update revenue ledger entry
        ledger_entry, _ = RevenueLedger.objects.update_or_create(
            payment=payment,
            course=course,
            defaults={
                "user": payment.user,
                "instructor": course.instructor,
                "gross_amount": course.price,
                "payment_status": payment.status,
                "payment_type": payment.payment_type or "Midtrans",
                "paid_at": paid_at,
            },
        )
        ledger_entries.append(ledger_entry)

    return ledger_entries


# ✓ Hitung saldo instruktur
def _get_instructor_balance(user):
    """Hitung total saldo instruktur yang bisa dicairkan
    
    Formula: Total Revenue - Total Withdrawals (yang sudah paid)
    """
    total_revenue = RevenueLedger.objects.filter(instructor=user).aggregate(total=Sum("gross_amount"))["total"] or 0
    total_paid_withdrawals = InstructorWithdraw.objects.filter(
        instructor=user,
        status=InstructorWithdraw.STATUS_PAID,
    ).aggregate(total=Sum("amount"))["total"] or 0
    return total_revenue - total_paid_withdrawals


# =============== CART HELPERS ===============
# ✓ Ambil course IDs dari cart session
def _get_cart_course_ids(request):
    """Ambil daftar course IDs dari session cart"""
    return list(request.session.get(CART_SESSION_KEY, []))


# ✓ Simpan course IDs ke cart session
def _save_cart_course_ids(request, course_ids):
    """Simpan course IDs ke session (untuk persistent cart)"""
    request.session[CART_SESSION_KEY] = list(course_ids)
    request.session.modified = True


# ✓ Convert harga ke integer (untuk Midtrans)
def _cart_price_to_int(price):
    """Convert Decimal price ke integer (cents)
    
    Contoh: 50000.50 Rp -> 5000050 cents
    """
    return int(Decimal(price).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ✓ Ambil course objects dari cart
def _get_cart_courses(request):
    """Ambil daftar Course objects dari cart session
    
    PENTING: Jika user sudah enroll ke course ini, otomatis remove dari cart
    """
    course_ids = _get_cart_course_ids(request)
    if not course_ids:
        return []

    courses = Course.objects.filter(pk__in=course_ids)
    course_map = {course.pk: course for course in courses}
    cart_courses = [course_map[course_id] for course_id in course_ids if course_id in course_map]

    # Auto-remove courses user sudah enroll
    if request.user.is_authenticated:
        enrolled_course_ids = set(
            Enrollment.objects.filter(user=request.user, course_id__in=course_ids).values_list("course_id", flat=True)
        )
        remaining_courses = [course for course in cart_courses if course.pk not in enrolled_course_ids]
        if len(remaining_courses) != len(cart_courses):
            _save_cart_course_ids(request, [course.pk for course in remaining_courses])
        return remaining_courses

    return cart_courses


# ✓ Hitung total harga cart
def _get_cart_total(cart_courses):
    """Hitung total harga semua course di cart"""
    return sum(course.price for course in cart_courses)


# =============== MIDTRANS PAYMENT HELPERS ===============
# ✓ Cek apakah Midtrans sudah dikonfigurasi
def _midtrans_is_configured():
    """Cek apakah Midtrans API keys sudah set di .env"""
    return bool(settings.MIDTRANS_SERVER_KEY and settings.MIDTRANS_CLIENT_KEY)


# ✓ Base URL Midtrans
def _midtrans_base_url():
    """Return base URL Midtrans (production atau sandbox)"""
    return "https://app.midtrans.com" if settings.MIDTRANS_IS_PRODUCTION else "https://app.sandbox.midtrans.com"


# ✓ Extract error dari Midtrans response
def _midtrans_error_payload(response):
    """Parse JSON response dari Midtrans"""
    if response is None:
        return None

    try:
        payload = response.json()
    except ValueError:
        payload = {"message": response.text[:1000]}

    return payload


# ✓ Extract error message dari Midtrans
def _midtrans_error_detail(payload, fallback):
    """Extract pesan error dari Midtrans response"""
    if isinstance(payload, dict):
        error_messages = payload.get("error_messages")
        if isinstance(error_messages, list) and error_messages:
            return "; ".join(str(message) for message in error_messages if message)

        for key in ("status_message", "message", "error_message"):
            value = payload.get(key)
            if value:
                return str(value)

    return fallback


# ✓ Generate Midtrans signature (untuk verify webhook)
def _midtrans_signature(order_id, status_code, gross_amount):
    """Generate SHA512 signature untuk verify Midtrans notification"""
    payload = f"{order_id}{status_code}{gross_amount}{settings.MIDTRANS_SERVER_KEY}".encode("utf-8")
    return hashlib.sha512(payload).hexdigest()


# ✓ Build item details untuk Midtrans
def _build_midtrans_item_details(cart_courses):
    """Build daftar item details untuk Midtrans API request"""
    return [
        {
            "id": str(course.pk),
            "price": _cart_price_to_int(course.price),
            "quantity": 1,
            "name": course.title[:50],
        }
        for course in cart_courses
    ]


def _cart_checkout_order_id(user, cart_courses):
    course_ids = ",".join(str(course.pk) for course in sorted(cart_courses, key=lambda course: course.pk))
    payload = f"{user.pk}:{course_ids}:{_get_cart_total(cart_courses)}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"SF-{user.pk}-{digest}"


def _activate_checkout_enrollments(payment):
    purchased_courses = []
    for course in _get_payment_courses(payment):
        if not course:
            continue

        enrollment, created = Enrollment.objects.get_or_create(
            user=payment.user,
            course=course,
            defaults={
                "granted_via": Enrollment.METHOD_PURCHASE,
                "amount_paid": course.price,
            },
        )
        if not created:
            enrollment.granted_via = Enrollment.METHOD_PURCHASE
            enrollment.amount_paid = course.price
            enrollment.save(update_fields=["granted_via", "amount_paid"])
        purchased_courses.append(course)

    if purchased_courses:
        invoice, invoice_created = Invoice.objects.get_or_create(
            invoice_number=payment.order_id,
            defaults={
                "user": payment.user,
                "amount_paid": payment.gross_amount,
                "payment_method": payment.payment_type or "Midtrans",
                "status": "Paid",
            }
        )
        if invoice_created:
            invoice.courses.set(purchased_courses)

    _record_revenue_ledger(payment)


def _sync_midtrans_payment(payment):
    response = requests.get(
        f"{_midtrans_base_url()}/v2/{payment.order_id}/status",
        auth=(settings.MIDTRANS_SERVER_KEY, ""),
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()

    transaction_status = str(payload.get("transaction_status", "")).lower()
    payment.transaction_id = str(payload.get("transaction_id", ""))
    payment.payment_type = str(payload.get("payment_type", ""))
    payment.raw_response = payload

    if transaction_status in {CartPayment.STATUS_SETTLEMENT, CartPayment.STATUS_CAPTURE}:
        payment.status = transaction_status
        payment.paid_at = payment.paid_at or timezone.now()
        _activate_checkout_enrollments(payment)
    elif transaction_status == CartPayment.STATUS_PENDING:
        payment.status = CartPayment.STATUS_PENDING
    elif transaction_status in {CartPayment.STATUS_DENY, CartPayment.STATUS_EXPIRE, CartPayment.STATUS_CANCEL}:
        payment.status = transaction_status
    elif transaction_status:
        payment.status = CartPayment.STATUS_ERROR

    payment.save(
        update_fields=[
            "status",
            "transaction_id",
            "payment_type",
            "raw_response",
            "paid_at",
            "updated_at",
        ]
    )

    return payment, transaction_status


def _midtrans_duplicate_order_response(payment):
    try:
        payment, transaction_status = _sync_midtrans_payment(payment)
    except requests.RequestException:
        transaction_status = ""

    if payment.status in {CartPayment.STATUS_SETTLEMENT, CartPayment.STATUS_CAPTURE}:
        return JsonResponse(
            {
                "order_id": payment.order_id,
                "detail": "Transaksi ini sudah selesai. Segarkan keranjang kamu.",
            },
            status=400,
        )

    if payment.status == CartPayment.STATUS_PENDING and payment.snap_token:
        return JsonResponse(
            {
                "order_id": payment.order_id,
                "token": payment.snap_token,
                "client_key": settings.MIDTRANS_CLIENT_KEY,
            }
        )

    return JsonResponse(
        {
            "order_id": payment.order_id,
            "detail": "Transaksi untuk order ini sudah dibuat di Midtrans. Tunggu beberapa saat lalu sinkronkan status.",
            "synced_status": transaction_status,
        },
        status=409,
    )


def _finalize_midtrans_payment(payment):
    payment.status = CartPayment.STATUS_SETTLEMENT
    payment.paid_at = payment.paid_at or timezone.now()
    payment.save(update_fields=["status", "paid_at", "updated_at"])
    _activate_checkout_enrollments(payment)

    return payment


def _reconcile_pending_midtrans_payments(user):
    pending_payments = CartPayment.objects.filter(
        user=user,
        status=CartPayment.STATUS_PENDING,
        created_at__gte=timezone.now() - timedelta(days=1),
    ).order_by("-created_at")[:5]

    for payment in pending_payments:
        try:
            _sync_midtrans_payment(payment)
        except requests.RequestException:
            continue


def _activate_direct_cart_enrollments(user, cart_courses, *, granted_via, payment_method, invoice_prefix):
    activated_courses = []

    with transaction.atomic():
        for course in cart_courses:
            _, created = Enrollment.objects.get_or_create(
                user=user,
                course=course,
                defaults={
                    "granted_via": granted_via,
                    "amount_paid": course.price,
                },
            )

            if created:
                activated_courses.append(course)

        if activated_courses:
            invoice_number = f"{invoice_prefix}-{user.pk}-{timezone.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}"
            invoice = Invoice.objects.create(
                user=user,
                invoice_number=invoice_number,
                amount_paid=sum(course.price for course in activated_courses),
                payment_method=payment_method,
                status="Paid",
            )
            invoice.courses.set(activated_courses)

    return activated_courses


def home_view(request):
    """Home page with basic info about users and courses."""
    total_users = User.objects.count() if request.user.is_authenticated else 0
    total_courses = Course.objects.count()
    total_students = Enrollment.objects.values("user_id").distinct().count()

    return render(
        request,
        "courses/home.html",
        {
            "total_users": total_users,
            "total_courses": total_courses,
            "total_students": total_students,
        },
    )


def discovery_view(request):
    query = request.GET.get("q", "").strip()
    courses = Course.objects.select_related("instructor").all()

    if query:
        courses = courses.filter(Q(title__icontains=query) | Q(description__icontains=query))

    return render(request, "courses/discovery.html", {"courses": courses, "query": query})


def course_detail_view(request, pk):
    course = get_object_or_404(Course, pk=pk)
    enrolled = False
    in_cart = False
    discussion_form = CourseDiscussionForm()
    review_form = CourseReviewForm()

    if request.user.is_authenticated:
        _reconcile_pending_midtrans_payments(request.user)
        enrolled = Enrollment.objects.filter(user=request.user, course=course).exists()
        in_cart = course.pk in _get_cart_course_ids(request)

    can_watch_video = _can_watch_course_video(request.user, course, enrolled=enrolled)

    discussions = course.discussions.select_related("user").order_by("created_at")
    reviews = course.reviews.select_related("user").order_by("-created_at")
    user_has_review = False

    if request.user.is_authenticated:
        user_has_review = course.reviews.filter(user=request.user).exists()

    if request.method == "POST":
        if not request.user.is_authenticated:
            messages.error(request, "Silakan login terlebih dahulu untuk berdiskusi atau mengulas.")
            return redirect(f"{reverse('accounts:login')}?next={request.path}")

        if not enrolled and not _has_dashboard_access(request.user):
            messages.error(request, "Hanya peserta course yang dapat mengirim diskusi dan ulasan.")
            return redirect("courses:course_detail", pk=course.pk)

        form_type = request.POST.get("form_type")
        if form_type == "discussion":
            discussion_form = CourseDiscussionForm(request.POST)
            if discussion_form.is_valid():
                discussion = discussion_form.save(commit=False)
                discussion.course = course
                discussion.user = request.user
                discussion.save()
                messages.success(request, "Pesan diskusi berhasil dikirim.")
                return redirect("courses:course_detail", pk=course.pk)
        elif form_type == "review":
            review_form = CourseReviewForm(request.POST)
            if review_form.is_valid():
                if user_has_review:
                    messages.error(request, "Kamu sudah memberikan ulasan untuk course ini.")
                else:
                    review = review_form.save(commit=False)
                    review.course = course
                    review.user = request.user
                    review.save()
                    messages.success(request, "Ulasan berhasil dikirim.")
                return redirect("courses:course_detail", pk=course.pk)

    return render(
        request,
        "courses/detail.html",
        {
            "course": course,
            "is_enrolled": enrolled,
            "in_cart": in_cart,
            "can_watch_video": can_watch_video,
            "discussion_form": discussion_form,
            "review_form": review_form,
            "discussions": discussions,
            "reviews": reviews,
            "user_has_review": user_has_review,
            "average_rating": course.average_rating,
            "review_count": course.review_count,
        },
    )


@login_required
@never_cache
def admin_dashboard_view(request):
    if not request.user.is_staff and not request.user.is_superuser:
        if getattr(request.user, "is_instructor", False):
            instructor_courses = (
                Course.objects.filter(instructor=request.user)
                .select_related("instructor")
                .annotate(enrollment_count=Count("enrollments", distinct=True))
                .order_by("-created_at")
            )
            recent_courses_paginator = Paginator(instructor_courses, 5)
            recent_courses_page_obj = recent_courses_paginator.get_page(request.GET.get("courses_page"))

            revenue_entries = (
                RevenueLedger.objects.filter(instructor=request.user)
                .select_related("user", "course", "payment")
                .order_by("-paid_at", "-created_at")
            )
            recent_revenue_paginator = Paginator(revenue_entries, 5)
            recent_revenue_page_obj = recent_revenue_paginator.get_page(request.GET.get("revenue_page"))
            withdraw_balance = _get_instructor_balance(request.user)
            latest_withdraw_requests = InstructorWithdraw.objects.filter(instructor=request.user).select_related("reviewed_by").order_by("-created_at")
            latest_withdraw_requests_paginator = Paginator(latest_withdraw_requests, 4)
            latest_withdraw_requests_page_obj = latest_withdraw_requests_paginator.get_page(request.GET.get("withdraw_page"))

            total_students = Enrollment.objects.filter(course__instructor=request.user).values("user").distinct().count()
            total_enrollments = Enrollment.objects.filter(course__instructor=request.user).count()
            total_revenue = RevenueLedger.objects.filter(instructor=request.user).aggregate(total=Sum("gross_amount"))["total"] or 0

            stats = {
                "total_courses": instructor_courses.count(),
                "total_students": total_students,
                "total_enrollments": total_enrollments,
                "active_courses": instructor_courses.filter(enrollments__isnull=False).distinct().count(),
                "total_revenue": total_revenue,
            }

            current_year = timezone.now().year
            monthly_data = (
                RevenueLedger.objects.filter(instructor=request.user)
                .annotate(effective_paid_at=Coalesce("paid_at", "created_at"))
                .filter(effective_paid_at__year=current_year)
                .annotate(month=ExtractMonth("effective_paid_at"))
                .values("month")
                .annotate(total=Sum("gross_amount"))
                .order_by("month")
            )

            month_names = {
                1: "Januari",
                2: "Februari",
                3: "Maret",
                4: "April",
                5: "Mei",
                6: "Juni",
                7: "Juli",
                8: "Agustus",
                9: "September",
                10: "Oktober",
                11: "November",
                12: "Desember",
            }

            monthly_revenue = {month_names[m]: 0.0 for m in range(1, 13)}
            for data in monthly_data:
                month_num = data["month"]
                total = float(data["total"]) if data["total"] is not None else 0.0
                if month_num in month_names:
                    monthly_revenue[month_names[month_num]] = total
            has_revenue_data = any(value > 0 for value in monthly_revenue.values())
            chart_max_value = max(max(monthly_revenue.values()), 1)
            chart_bars = []
            for label, value in monthly_revenue.items():
                percentage = round((value / chart_max_value) * 100, 2) if chart_max_value else 0
                chart_bars.append(
                    {
                        "label": label,
                        "short_label": label[:3],
                        "value": value,
                        "percentage": percentage,
                    }
                )

            chart_labels = [bar["label"] for bar in chart_bars]
            chart_data = [bar["value"] for bar in chart_bars]

            return render(
                request,
                "dashboard/instructor_index.html",
                {
                    "dashboard_owner": request.user.get_full_name() or request.user.username,
                    "stats": stats,
                    "balance": withdraw_balance,
                    "recent_courses_page_obj": recent_courses_page_obj,
                    "recent_revenue_page_obj": recent_revenue_page_obj,
                    "latest_withdraw_requests": latest_withdraw_requests,
                    "current_year": current_year,
                    "chart_title": "Monthly revenue",
                    "chart_metric_label": "Revenue (IDR)",
                    "has_revenue_data": has_revenue_data,
                    "chart_bars": chart_bars,
                    "chart_max_value": chart_max_value,
                    "chart_labels": json.dumps(chart_labels),
                    "chart_data": json.dumps(chart_data),
                    "latest_withdraw_requests": latest_withdraw_requests_page_obj,
                    "latest_withdraw_requests_page_obj": latest_withdraw_requests_page_obj,
                    "active_nav": "dashboard",
                },
            )

        return redirect("courses:student_dashboard")

    student_users = User.objects.filter(enrollments__isnull=False).distinct()
    recent_courses = (
        Course.objects.select_related("instructor")
        .annotate(enrollment_count=Count("enrollments", distinct=True))
        .order_by("-created_at")
    )
    recent_courses_paginator = Paginator(recent_courses, 5)
    courses_page_number = request.GET.get("courses_page")
    recent_courses_page_obj = recent_courses_paginator.get_page(courses_page_number)

    recent_enrollments = (
        Enrollment.objects.select_related("user", "course")
        .order_by("-created_at")
    )
    recent_enrollments_paginator = Paginator(recent_enrollments, 5)
    enrollments_page_number = request.GET.get("enrollments_page")
    recent_enrollments_page_obj = recent_enrollments_paginator.get_page(enrollments_page_number)

    stats = {
        "total_users": User.objects.count(),
        "total_courses": Course.objects.count(),
        "total_students": student_users.count(),
        "total_enrollments": Enrollment.objects.count(),
    }

    # Calculate monthly income data for the current year from revenue ledger records
    current_year = timezone.now().year
    monthly_data = (
        RevenueLedger.objects.annotate(effective_paid_at=Coalesce("paid_at", "created_at"))
        .filter(effective_paid_at__year=current_year)
        .annotate(month=ExtractMonth("effective_paid_at"))
        .values("month")
        .annotate(total=Sum("gross_amount"))
        .order_by("month")
    )

    month_names = {
        1: "Januari",
        2: "Februari",
        3: "Maret",
        4: "April",
        5: "Mei",
        6: "Juni",
        7: "Juli",
        8: "Agustus",
        9: "September",
        10: "Oktober",
        11: "November",
        12: "Desember",
    }

    monthly_income = {month_names[m]: 0.0 for m in range(1, 13)}
    for data in monthly_data:
        month_num = data["month"]
        total = float(data["total"]) if data["total"] is not None else 0.0
        if month_num in month_names:
            monthly_income[month_names[month_num]] = total
    has_chart_data = any(value > 0 for value in monthly_income.values())

    chart_labels = list(monthly_income.keys())
    chart_data = list(monthly_income.values())

    return render(
        request,
        "dashboard/index.html",
        {
            "stats": stats,
            "balance": 0,
            "recent_courses_page_obj": recent_courses_page_obj,
            "recent_enrollments_page_obj": recent_enrollments_page_obj,
            "current_year": current_year,
            "chart_labels": json.dumps(chart_labels),
            "chart_data": json.dumps(chart_data),
            "has_chart_data": has_chart_data,
            "active_nav": "dashboard",
        },
    )


@login_required
@user_passes_test(lambda user: user.is_staff)
def student_summary_view(request):
    student_users = User.objects.filter(enrollments__isnull=False).distinct().order_by("-date_joined")
    paginator = Paginator(student_users, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    recent_students = Enrollment.objects.select_related("user", "course").order_by("-created_at")
    recent_students_paginator = Paginator(recent_students, 10)
    recent_page_number = request.GET.get("recent_page")
    recent_page_obj = recent_students_paginator.get_page(recent_page_number)

    stats = {
        "total_students": student_users.count(),
        "total_enrollments": Enrollment.objects.count(),
        "recent_joined": student_users.filter(date_joined__isnull=False).count(),
    }

    return render(
        request,
        "dashboard/students.html",
        {
            "active_nav": "students",
            "stats": stats,
            "page_obj": page_obj,
            "recent_page_obj": recent_page_obj,
            "recent_students": recent_students,
        },
    )


@login_required
def withdraw_request_view(request):
    if not getattr(request.user, "is_instructor", False):
        return redirect("courses:student_dashboard")

    balance = _get_instructor_balance(request.user)
    pending_requests = InstructorWithdraw.objects.filter(instructor=request.user, status=InstructorWithdraw.STATUS_PENDING)
    latest_requests = InstructorWithdraw.objects.filter(instructor=request.user).select_related("reviewed_by").order_by("-created_at")
    latest_requests_paginator = Paginator(latest_requests, 5)
    latest_requests_page_obj = latest_requests_paginator.get_page(request.GET.get("page"))

    if request.method == "POST":
        form = InstructorWithdrawForm(request.POST, available_balance=balance)
        if form.is_valid():
            withdraw_request = form.save(commit=False)
            withdraw_request.instructor = request.user
            withdraw_request.balance_snapshot = balance
            withdraw_request.status = InstructorWithdraw.STATUS_PENDING
            withdraw_request.save()
            messages.success(request, "Request withdraw berhasil dikirim dan menunggu review admin.")
            return redirect("courses:withdraw_request")
        amount_errors = form.errors.as_data().get("amount", [])
        if any(error.code == "exceeds_balance" for error in amount_errors):
            messages.error(request, amount_errors[0].message)
    else:
        form = InstructorWithdrawForm(available_balance=balance)

    return render(
        request,
        "courses/withdraw_request.html",
        {
            "form": form,
            "balance": balance,
            "pending_count": pending_requests.count(),
            "latest_requests": latest_requests_page_obj,
            "page_obj": latest_requests_page_obj,
            "active_nav": "withdraw_request",
        },
    )


@login_required
@user_passes_test(lambda user: user.is_staff)
def manage_withdraw_request_list(request):
    withdraw_requests = InstructorWithdraw.objects.select_related("instructor", "reviewed_by").order_by("-created_at")

    query = request.GET.get("q", "").strip()
    if query:
        withdraw_requests = withdraw_requests.filter(
            Q(instructor__username__icontains=query)
            | Q(instructor__email__icontains=query)
            | Q(account_name__icontains=query)
            | Q(account_number__icontains=query)
        )

    status_filter = request.GET.get("status", "").strip()
    if status_filter:
        withdraw_requests = withdraw_requests.filter(status__iexact=status_filter)

    if request.method == "POST":
        withdraw_request = get_object_or_404(
            InstructorWithdraw.objects.select_related("instructor"),
            pk=request.POST.get("withdraw_id"),
        )
        action = request.POST.get("action")
        review_note = request.POST.get("review_note", "").strip()

        if withdraw_request.status != InstructorWithdraw.STATUS_PENDING:
            messages.info(request, "Request withdraw ini sudah diproses sebelumnya.")
            return redirect("dashboard:withdrawals")

        withdraw_request.review_note = review_note
        withdraw_request.reviewed_by = request.user
        withdraw_request.reviewed_at = timezone.now()

        if action == "approve":
            current_balance = _get_instructor_balance(withdraw_request.instructor)
            if withdraw_request.amount > current_balance:
                messages.error(request, "Saldo instructor tidak cukup untuk approve withdraw ini.")
                return redirect("dashboard:withdrawals")

            withdraw_request.status = InstructorWithdraw.STATUS_PAID
            withdraw_request.paid_at = timezone.now()
            withdraw_request.save(update_fields=["status", "review_note", "reviewed_by", "reviewed_at", "paid_at", "updated_at"])
            messages.success(request, f"Withdraw {withdraw_request.instructor.username} berhasil di-approve dan ditandai PAID.")
        elif action == "reject":
            withdraw_request.status = InstructorWithdraw.STATUS_REJECTED
            withdraw_request.save(update_fields=["status", "review_note", "reviewed_by", "reviewed_at", "updated_at"])
            messages.success(request, f"Withdraw {withdraw_request.instructor.username} ditolak.")
        else:
            messages.error(request, "Aksi review tidak valid.")

        return redirect("dashboard:withdrawals")

    paginator = Paginator(withdraw_requests, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "dashboard/manage_withdrawals.html",
        {
            "page_obj": page_obj,
            "query": query,
            "status_filter": status_filter,
            "active_nav": "withdrawals",
            "balance_summary": _get_instructor_balance(request.user),
        },
    )


@login_required
@user_passes_test(lambda user: user.is_staff)
def instructor_request_list_view(request):
    if request.method == "POST":
        application = get_object_or_404(
            InstructorApplication.objects.select_related("user"),
            pk=request.POST.get("application_id"),
        )
        action = request.POST.get("action")
        review_note = request.POST.get("review_note", "").strip()

        if application.status != InstructorApplication.STATUS_PENDING:
            messages.info(request, "Request ini sudah diproses sebelumnya.")
            return redirect("dashboard:instructor_requests")

        application.review_note = review_note
        application.reviewed_by = request.user
        application.reviewed_at = timezone.now()

        if action == "approve":
            application.status = InstructorApplication.STATUS_APPROVED
            application.save(update_fields=["status", "review_note", "reviewed_by", "reviewed_at", "updated_at"])
            application.user.role = User.ROLE_INSTRUCTOR
            application.user.save(update_fields=["role"])
            messages.success(request, f"{application.full_name} berhasil di-approve sebagai instructor.")
        elif action == "reject":
            application.status = InstructorApplication.STATUS_REJECTED
            application.save(update_fields=["status", "review_note", "reviewed_by", "reviewed_at", "updated_at"])
            messages.success(request, f"{application.full_name} ditolak.")
        else:
            messages.error(request, "Aksi review tidak valid.")

        return redirect("dashboard:instructor_requests")

    applications = InstructorApplication.objects.select_related("user", "reviewed_by").order_by("-created_at")
    pending_count = applications.filter(status=InstructorApplication.STATUS_PENDING).count()

    paginator = Paginator(applications, 5)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "dashboard/instructor_requests.html",
        {
            "page_obj": page_obj,
            "pending_count": pending_count,
            "active_nav": "instructor_requests",
        },
    )


@login_required
def student_dashboard_view(request):
    _reconcile_pending_midtrans_payments(request.user)
    enrollments = Enrollment.objects.filter(user=request.user).select_related("course")
    return render(request, "courses/student_dashboard.html", {"enrollments": enrollments})


@login_required
def history_view(request):
    _reconcile_pending_midtrans_payments(request.user)
    invoices_list = Invoice.objects.filter(user=request.user).prefetch_related("courses")
    paginator = Paginator(invoices_list, 5)  # Show 5 invoices per page
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    return render(request, "courses/student_dashboard.html", {"page_obj": page_obj})


@login_required
def my_courses_view(request):
    _reconcile_pending_midtrans_payments(request.user)
    enrollments = Enrollment.objects.filter(user=request.user).select_related("course")
    return render(request, "courses/my_courses.html", {"enrollments": enrollments})


@login_required
def cart_view(request):
    cart_courses = _get_cart_courses(request)
    return render(
        request,
        "courses/cart.html",
        {
            "cart_courses": cart_courses,
            "cart_count": len(cart_courses),
            "cart_total": _get_cart_total(cart_courses),
            "midtrans_enabled": _midtrans_is_configured(),
            "midtrans_client_key": settings.MIDTRANS_CLIENT_KEY,
            "midtrans_snap_url": settings.MIDTRANS_SNAP_URL,
        },
    )


@login_required
def add_to_cart_view(request, pk):
    if request.method != "POST":
        return redirect("courses:course_detail", pk=pk)

    course = get_object_or_404(Course, pk=pk)

    if Enrollment.objects.filter(user=request.user, course=course).exists():
        messages.info(request, "Course ini sudah ada di kelas kamu.")
        return redirect("courses:course_detail", pk=course.pk)

    course_ids = _get_cart_course_ids(request)
    if course.pk in course_ids:
        messages.info(request, "Course ini sudah ada di keranjang.")
        return redirect("courses:cart")

    course_ids.append(course.pk)
    _save_cart_course_ids(request, course_ids)
    messages.success(request, "Course ditambahkan ke keranjang.")
    return redirect("courses:cart")


@login_required
def remove_from_cart_view(request, pk):
    if request.method != "POST":
        return redirect("courses:cart")

    course_ids = [course_id for course_id in _get_cart_course_ids(request) if course_id != pk]
    _save_cart_course_ids(request, course_ids)
    messages.success(request, "Course dihapus dari keranjang.")
    return redirect("courses:cart")


@login_required
def cart_confirm_view(request):
    cart_courses = _get_cart_courses(request)

    if not cart_courses:
        messages.info(request, "Keranjang kamu masih kosong.")
        return redirect("courses:cart")

    if request.method == "POST":
        cart_total = _get_cart_total(cart_courses)
        if cart_total <= 0:
            activated_courses = _activate_direct_cart_enrollments(
                request.user,
                cart_courses,
                granted_via=Enrollment.METHOD_FREE,
                payment_method="Free Enrollment",
                invoice_prefix="INV-FREE",
            )
        else:
            activated_courses = _activate_direct_cart_enrollments(
                request.user,
                cart_courses,
                granted_via=Enrollment.METHOD_PURCHASE,
                payment_method="Direct Confirm",
                invoice_prefix="SF",
            )

        _save_cart_course_ids(request, [])

        if activated_courses:
            messages.success(request, "Keranjang sudah dikonfirmasi dan kursus berhasil diaktifkan.")
        else:
            messages.info(request, "Semua course di keranjang sudah terdaftar.")

        return redirect("courses:my_courses")

    return render(
        request,
        "courses/cart_confirm.html",
        {
            "cart_courses": cart_courses,
            "cart_count": len(cart_courses),
            "cart_total": _get_cart_total(cart_courses),
        },
    )


@login_required
@require_POST
def midtrans_checkout_view(request):
    cart_courses = _get_cart_courses(request)
    if not cart_courses:
        return JsonResponse({"detail": "Keranjang kamu masih kosong."}, status=400)

    total_amount = _get_cart_total(cart_courses)
    if total_amount <= 0:
        activated_courses = _activate_direct_cart_enrollments(
            request.user,
            cart_courses,
            granted_via=Enrollment.METHOD_FREE,
            payment_method="Free Enrollment",
            invoice_prefix="INV-FREE",
        )
        _save_cart_course_ids(request, [])

        if activated_courses:
            return JsonResponse(
                {
                    "free_checkout": True,
                    "redirect_url": reverse("courses:my_courses"),
                    "detail": "Course gratis berhasil di-claim.",
                }
            )

        return JsonResponse({"detail": "Semua course di keranjang sudah terdaftar."}, status=400)

    if not _midtrans_is_configured():
        return JsonResponse({"detail": "MIDTRANS_SERVER_KEY dan MIDTRANS_CLIENT_KEY belum diatur."}, status=400)

    order_id = _cart_checkout_order_id(request.user, cart_courses)
    payment, created = CartPayment.objects.get_or_create(
        order_id=order_id,
        defaults={
            "user": request.user,
            "course_ids": [course.pk for course in cart_courses],
            "gross_amount": total_amount,
            "status": CartPayment.STATUS_PENDING,
        },
    )

    if not created:
        if payment.status in {CartPayment.STATUS_SETTLEMENT, CartPayment.STATUS_CAPTURE}:
            return JsonResponse({"detail": "Transaksi ini sudah selesai. Segarkan keranjang kamu."}, status=400)

        if payment.status == CartPayment.STATUS_PENDING and payment.snap_token:
            return JsonResponse(
                {
                    "order_id": payment.order_id,
                    "token": payment.snap_token,
                    "client_key": settings.MIDTRANS_CLIENT_KEY,
                }
            )

        if payment.status == CartPayment.STATUS_PENDING and not payment.snap_token:
            return JsonResponse({"detail": "Checkout sedang diproses. Coba lagi sebentar."}, status=409)

        if payment.status == CartPayment.STATUS_ERROR and isinstance(payment.raw_response, dict):
            last_error_detail = str(payment.raw_response.get("detail", ""))
            if "order_id has already been taken" in last_error_detail.lower():
                return _midtrans_duplicate_order_response(payment)

    try:
        response = requests.post(
            f"{_midtrans_base_url()}/snap/v1/transactions",
            auth=(settings.MIDTRANS_SERVER_KEY, ""),
            json={
                "transaction_details": {
                    "order_id": order_id,
                    "gross_amount": _cart_price_to_int(total_amount),
                },
                "item_details": _build_midtrans_item_details(cart_courses),
                "customer_details": {
                    "first_name": getattr(request.user, "first_name", "") or request.user.username,
                    "last_name": getattr(request.user, "last_name", ""),
                    "email": getattr(request.user, "email", "") or "",
                },
            },
            timeout=20,
        )
        response.raise_for_status()
        response_data = response.json()
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        response_payload = _midtrans_error_payload(response)
        error_detail = _midtrans_error_detail(response_payload, "Gagal membuat transaksi Midtrans.")
        error_status = response.status_code if response is not None else 502

        payment.status = CartPayment.STATUS_ERROR
        payment.raw_response = {
            "error": response_payload,
            "http_status": error_status,
            "detail": error_detail,
        }
        payment.save(update_fields=["status", "raw_response", "updated_at"])

        if response is not None and error_status < 500:
            if "order_id has already been taken" in error_detail.lower():
                return _midtrans_duplicate_order_response(payment)

            return JsonResponse({"detail": error_detail}, status=error_status)

        return JsonResponse({"detail": error_detail}, status=502)

    payment.user = request.user
    payment.course_ids = [course.pk for course in cart_courses]
    payment.gross_amount = total_amount
    payment.status = CartPayment.STATUS_PENDING
    payment.snap_token = response_data.get("token", "")
    payment.raw_response = response_data
    payment.save(
        update_fields=[
            "user",
            "course_ids",
            "gross_amount",
            "status",
            "snap_token",
            "raw_response",
            "updated_at",
        ]
    )

    return JsonResponse(
        {
            "order_id": payment.order_id,
            "token": payment.snap_token,
            "client_key": settings.MIDTRANS_CLIENT_KEY,
        }
    )


@login_required
@require_POST
def midtrans_sync_view(request):
    if not settings.MIDTRANS_SERVER_KEY:
        return JsonResponse({"detail": "Midtrans belum dikonfigurasi."}, status=400)

    order_id = str(request.POST.get("order_id", "")).strip()
    if not order_id:
        return JsonResponse({"detail": "order_id wajib diisi."}, status=400)

    payment = get_object_or_404(CartPayment, order_id=order_id, user=request.user)

    try:
        payment, transaction_status = _sync_midtrans_payment(payment)
    except requests.RequestException:
        return JsonResponse({"detail": "Gagal sinkronisasi status Midtrans."}, status=502)

    session_course_ids = request.session.get(CART_SESSION_KEY, [])
    remaining_course_ids = [course_id for course_id in session_course_ids if course_id not in payment.course_ids]
    if transaction_status in {CartPayment.STATUS_SETTLEMENT, CartPayment.STATUS_CAPTURE}:
        _save_cart_course_ids(request, remaining_course_ids)

    return JsonResponse(
        {
            "ok": True,
            "status": payment.status,
            "activated": payment.status in {CartPayment.STATUS_SETTLEMENT, CartPayment.STATUS_CAPTURE},
            "redirect_url": reverse("courses:my_courses"),
        }
    )


@login_required
@require_POST
def midtrans_complete_view(request):
    if not settings.MIDTRANS_SERVER_KEY:
        return JsonResponse({"detail": "Midtrans belum dikonfigurasi."}, status=400)

    order_id = str(request.POST.get("order_id", "")).strip()
    if not order_id:
        return JsonResponse({"detail": "order_id wajib diisi."}, status=400)

    payment = get_object_or_404(CartPayment, order_id=order_id, user=request.user)

    try:
        payment, transaction_status = _sync_midtrans_payment(payment)
    except requests.RequestException:
        transaction_status = ""

    if payment.status not in {CartPayment.STATUS_SETTLEMENT, CartPayment.STATUS_CAPTURE}:
        _finalize_midtrans_payment(payment)

    session_course_ids = request.session.get(CART_SESSION_KEY, [])
    remaining_course_ids = [course_id for course_id in session_course_ids if course_id not in payment.course_ids]
    _save_cart_course_ids(request, remaining_course_ids)

    return JsonResponse(
        {
            "ok": True,
            "status": payment.status,
            "activated": True,
            "redirect_url": reverse("courses:my_courses"),
            "synced_status": transaction_status,
        }
    )


@csrf_exempt
@require_POST
def midtrans_notification_view(request):
    if not settings.MIDTRANS_SERVER_KEY:
        return JsonResponse({"detail": "Midtrans belum dikonfigurasi."}, status=400)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Payload tidak valid."}, status=400)

    order_id = payload.get("order_id", "")
    status_code = str(payload.get("status_code", ""))
    gross_amount = str(payload.get("gross_amount", ""))
    signature_key = payload.get("signature_key", "")

    if not order_id or signature_key != _midtrans_signature(order_id, status_code, gross_amount):
        return HttpResponseForbidden("Invalid Midtrans signature")

    payment = get_object_or_404(CartPayment, order_id=order_id)
    transaction_status = str(payload.get("transaction_status", "")).lower()
    payment.transaction_id = str(payload.get("transaction_id", ""))
    payment.payment_type = str(payload.get("payment_type", ""))
    payment.raw_response = payload

    if transaction_status in {CartPayment.STATUS_SETTLEMENT, CartPayment.STATUS_CAPTURE}:
        payment.status = transaction_status
        payment.paid_at = payment.paid_at or timezone.now()
        _activate_checkout_enrollments(payment)
    elif transaction_status == CartPayment.STATUS_PENDING:
        payment.status = CartPayment.STATUS_PENDING
    elif transaction_status in {CartPayment.STATUS_DENY, CartPayment.STATUS_EXPIRE, CartPayment.STATUS_CANCEL}:
        payment.status = transaction_status
    elif transaction_status:
        payment.status = CartPayment.STATUS_ERROR

    payment.save(
        update_fields=[
            "status",
            "transaction_id",
            "payment_type",
            "raw_response",
            "paid_at",
            "updated_at",
        ]
    )

    return JsonResponse({"ok": True})


@login_required
def enroll_course_view(request, pk):
    if request.method != "POST":
        return redirect("courses:course_detail", pk=pk)

    course = get_object_or_404(Course, pk=pk)

    if Enrollment.objects.filter(user=request.user, course=course).exists():
        messages.info(request, "Anda sudah terdaftar dalam kursus ini.")
        return redirect("courses:course_detail", pk=course.pk)

    Enrollment.objects.create(
        user=request.user,
        course=course,
        granted_via=Enrollment.METHOD_FREE,
        amount_paid=0,
    )
    import datetime
    import random
    invoice_number = f"INV-FREE-{request.user.pk}-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
    invoice = Invoice.objects.create(
        user=request.user,
        invoice_number=invoice_number,
        amount_paid=0,
        payment_method="Free Enrollment",
        status="Paid",
    )
    invoice.courses.add(course)
    messages.success(request, "Anda sekarang terdaftar dalam kursus ini.")
    return redirect("courses:my_courses")


@login_required
@user_passes_test(_has_dashboard_access)
def manage_course_list(request):
    courses_list = _manageable_courses_queryset(request.user)
    paginator = Paginator(courses_list, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    balance = _get_instructor_balance(request.user) if getattr(request.user, "is_instructor", False) else 0
    return render(
        request,
        "dashboard/manage_courses.html",
        {"page_obj": page_obj, "active_nav": "manage_courses", "balance": balance},
    )


@login_required
@user_passes_test(_has_dashboard_access)
def manage_course_add(request):
    if request.method == "POST":
        form = CourseForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            course = form.save(commit=False)
            if not request.user.is_staff and not request.user.is_superuser:
                course.instructor = request.user
            course.save()
            messages.success(request, "Course berhasil ditambahkan.")
            return redirect("dashboard:manage_courses")
    else:
        form = CourseForm(user=request.user)
    return render(request, "dashboard/manage_course_form.html", {"form": form, "action": "Tambah Course"})


@login_required
@user_passes_test(_has_dashboard_access)
def manage_course_edit(request, pk):
    course = _manageable_course_or_404(request.user, pk)
    if request.method == "POST":
        form = CourseForm(request.POST, request.FILES, instance=course, user=request.user)
        if form.is_valid():
            course = form.save(commit=False)
            if not request.user.is_staff and not request.user.is_superuser:
                course.instructor = request.user
            course.save()
            messages.success(request, "Course berhasil diperbarui.")
            return redirect("dashboard:manage_courses")
    else:
        form = CourseForm(instance=course, user=request.user)
    return render(request, "dashboard/manage_course_form.html", {"form": form, "action": "Edit Course"})


@login_required
@user_passes_test(_has_dashboard_access)
def manage_course_delete(request, pk):
    course = _manageable_course_or_404(request.user, pk)
    if request.method == "POST":
        course.delete()
        messages.success(request, "Course berhasil dihapus.")
        return redirect("dashboard:manage_courses")
    return render(request, "dashboard/manage_course_confirm_delete.html", {"course": course})


@login_required
@user_passes_test(lambda user: user.is_staff)
def manage_transaction_list(request):
    invoices_list = Invoice.objects.select_related("user").prefetch_related("courses").all()

    # Search functionality
    query = request.GET.get("q", "").strip()
    if query:
        invoices_list = invoices_list.filter(
            Q(invoice_number__icontains=query) |
            Q(user__username__icontains=query) |
            Q(user__email__icontains=query) |
            Q(courses__title__icontains=query)
        ).distinct()

    # Filter by status
    status_filter = request.GET.get("status", "").strip()
    if status_filter:
        invoices_list = invoices_list.filter(status__iexact=status_filter)

    # Pagination
    paginator = Paginator(invoices_list, 10)  # 10 invoices per page
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "dashboard/manage_transactions.html",
        {
            "page_obj": page_obj,
            "query": query,
            "status_filter": status_filter,
            "active_nav": "transactions",
        },
    )

