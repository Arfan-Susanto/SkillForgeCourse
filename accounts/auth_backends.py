from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

from .models import User


class EmailOrUsernameBackend(ModelBackend):
    def authenticate(self, request, username=None, email=None, password=None, **kwargs):
        identifier = (email or username or kwargs.get(User.USERNAME_FIELD) or "").strip()
        if not identifier or password is None:
            return None

        user = User.objects.filter(Q(email__iexact=identifier) | Q(username__iexact=identifier)).first()
        if user is None:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None