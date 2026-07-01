from django.urls import path

from .views import (
    admin_dashboard_view,
    manage_course_add,
    manage_course_delete,
    manage_course_edit,
    manage_course_list,
    instructor_request_list_view,
    manage_transaction_list,
    manage_withdraw_request_list,
    student_summary_view,
)

app_name = "dashboard"

urlpatterns = [
    path("", admin_dashboard_view, name="index"),
    path("students/", student_summary_view, name="students"),
    path("instructor-requests/", instructor_request_list_view, name="instructor_requests"),
    path("withdrawals/", manage_withdraw_request_list, name="withdrawals"),
    path("manage/courses/", manage_course_list, name="manage_courses"),
    path("manage/courses/add/", manage_course_add, name="manage_course_add"),
    path("manage/courses/<int:pk>/edit/", manage_course_edit, name="manage_course_edit"),
    path("manage/courses/<int:pk>/delete/", manage_course_delete, name="manage_course_delete"),
    path("transaction/", manage_transaction_list, name="transactions"),
]