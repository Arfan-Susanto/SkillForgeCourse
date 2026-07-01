from django.contrib.auth import get_user_model
from django.utils.text import slugify

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        # If the social account already exists or user is logged in, let allauth handle it.
        if sociallogin.is_existing or request.user.is_authenticated:
            return

        email = (sociallogin.user.email or sociallogin.account.extra_data.get("email") or "").strip().lower()
        if not email:
            return

        user_model = get_user_model()
        existing_user = user_model.objects.filter(email__iexact=email).first()
        if existing_user is None:
            return

        # Link Google account to existing local account and continue login.
        sociallogin.connect(request, existing_user)

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)

        if getattr(user, "username", ""):
            return user

        user_model = get_user_model()
        base_username = data.get("username") or data.get("email", "").split("@")[0] or "user"
        base_username = slugify(base_username).replace("-", "")[:20] or "user"

        candidate = base_username
        suffix = 0
        while user_model.objects.filter(username__iexact=candidate).exists():
            suffix += 1
            candidate = f"{base_username}{suffix}"[:150]

        user.username = candidate
        return user
