from django.urls import path
from django.views.generic import RedirectView

from .views import (
    course_detail_view,
    discovery_view,
    enroll_course_view,
    admin_dashboard_view,
    add_to_cart_view,
    cart_view,
    cart_confirm_view,
    midtrans_checkout_view,
    midtrans_sync_view,
    midtrans_complete_view,
    midtrans_notification_view,
    remove_from_cart_view,
    history_view,
    my_courses_view,
    student_dashboard_view,
    manage_course_list,
    manage_course_add,
    manage_course_edit,
    manage_course_delete,
    withdraw_request_view,
)

app_name = "courses"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="courses:discovery", permanent=False)),
    path("browse/", discovery_view, name="discovery"),
    path("courses/<int:pk>/", course_detail_view, name="course_detail"),
    path("dashboard/", admin_dashboard_view, name="admin_dashboard"),
    path("dashboard/student/", student_dashboard_view, name="student_dashboard"),
    path("dashboard/history/", history_view, name="history"),
    path("dashboard/withdraw/", withdraw_request_view, name="withdraw_request"),
    path("dashboard/cart/", cart_view, name="cart"),
    path("dashboard/cart/confirm/", cart_confirm_view, name="cart_confirm"),
    path("dashboard/cart/midtrans/checkout/", midtrans_checkout_view, name="midtrans_checkout"),
    path("dashboard/cart/midtrans/sync/", midtrans_sync_view, name="midtrans_sync"),
    path("dashboard/cart/midtrans/complete/", midtrans_complete_view, name="midtrans_complete"),
    path("dashboard/cart/<int:pk>/remove/", remove_from_cart_view, name="cart_remove"),
    path("dashboard/my-courses/", my_courses_view, name="my_courses"),
    path("courses/<int:pk>/add-to-cart/", add_to_cart_view, name="add_to_cart"),
    # Manage courses (CRUD) for staff
    path("manage/courses/", manage_course_list, name="manage_courses"),
    path("manage/courses/add/", manage_course_add, name="manage_course_add"),
    path("manage/courses/<int:pk>/edit/", manage_course_edit, name="manage_course_edit"),
    path("manage/courses/<int:pk>/delete/", manage_course_delete, name="manage_course_delete"),
    path("courses/<int:pk>/enroll/", enroll_course_view, name="enroll_course"),
    path("payment/midtrans/notification/", midtrans_notification_view, name="midtrans_notification"),
]
