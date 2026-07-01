from django.contrib.auth.decorators import login_required


def student_required(view_func):
    """Decorator to require authentication. All authenticated users are considered students."""
    return login_required(view_func)
