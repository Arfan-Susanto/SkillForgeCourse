import logging
import secrets
from datetime import timedelta
from smtplib import SMTPException

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.utils import timezone

from .models import OTP

logger = logging.getLogger(__name__)


def generate_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def otp_expiry_delta() -> timedelta:
    return timedelta(minutes=getattr(settings, "OTP_EXPIRY_MINUTES", 5))


def otp_cooldown_delta() -> timedelta:
    return timedelta(seconds=getattr(settings, "OTP_COOLDOWN_SECONDS", 60))


def otp_max_attempts() -> int:
    return int(getattr(settings, "OTP_MAX_VERIFY_ATTEMPTS", 5))


def hash_otp_code(otp_code: str) -> str:
    return make_password(otp_code)


def verify_otp_hash(raw_otp: str, hashed_otp: str) -> bool:
    return check_password(raw_otp, hashed_otp)


def can_request_new_otp(user, purpose: str) -> tuple[bool, int]:
    latest_otp = OTP.objects.filter(user=user, purpose=purpose).order_by("-created_at").first()
    if latest_otp is None:
        return True, 0

    next_allowed_at = latest_otp.created_at + otp_cooldown_delta()
    if timezone.now() < next_allowed_at:
        remaining_seconds = int((next_allowed_at - timezone.now()).total_seconds())
        return False, max(remaining_seconds, 1)

    return True, 0


def issue_otp(user, purpose: str) -> tuple[OTP, bool]:
    otp_code = generate_otp_code()
    expires_at = timezone.now() + otp_expiry_delta()

    OTP.objects.filter(user=user, purpose=purpose, is_used=False, is_verified=False).update(is_used=True)

    otp = OTP.objects.create(
        user=user,
        purpose=purpose,
        otp_code=hash_otp_code(otp_code),
        expires_at=expires_at,
    )

    email_sent = send_otp_email(user.email, otp_code, expires_at, purpose=purpose)
    if not email_sent:
        OTP.objects.filter(pk=otp.pk).update(is_used=True)
        logger.warning("OTP created but email delivery failed for user_id=%s otp_id=%s purpose=%s", user.id, otp.id, purpose)
    logger.info("OTP issued for user_id=%s otp_id=%s purpose=%s", user.id, otp.id, purpose)
    return otp, email_sent


def send_otp_email(email: str, otp_code: str, expires_at, purpose: str):
    context_title = "login" if purpose == OTP.PURPOSE_LOGIN else "password reset"
    subject = f"Your SkillForge OTP for {context_title}"
    message = (
        f"Your one-time password is {otp_code}.\n\n"
        f"This OTP is for {context_title}.\n"
        f"It expires at {timezone.localtime(expires_at).strftime('%Y-%m-%d %H:%M:%S %Z')} "
        f"and is valid for {getattr(settings, 'OTP_EXPIRY_MINUTES', 5)} minutes.\n\n"
        "If you did not request this, you can ignore this message."
    )
    logger.info("Sending OTP email to=%s purpose=%s subject=%s", email, purpose, subject)
    try:
        sent_count = send_mail(subject, message, getattr(settings, "DEFAULT_FROM_EMAIL", None), [email], fail_silently=False)
    except SMTPException:
        logger.exception("OTP email delivery failed to=%s purpose=%s", email, purpose)
        return False

    logger.info("OTP email send_mail completed to=%s purpose=%s sent_count=%s", email, purpose, sent_count)
    return sent_count > 0


def verify_user_otp(user, raw_otp: str, purpose: str):
    otp = OTP.objects.filter(user=user, purpose=purpose, is_used=False).order_by("-created_at").first()
    if otp is None:
        return None, "No active OTP found.", "missing"

    if otp.is_expired:
        otp.is_used = True
        otp.save(update_fields=["is_used"])
        return None, "OTP has expired.", "expired"

    if otp.failed_attempts >= otp_max_attempts():
        otp.is_used = True
        otp.save(update_fields=["is_used"])
        return None, "OTP blocked after too many failed attempts.", "locked"

    if not verify_otp_hash(raw_otp, otp.otp_code):
        otp.failed_attempts += 1
        if otp.failed_attempts >= otp_max_attempts():
            otp.is_used = True
        otp.save(update_fields=["failed_attempts", "is_used"])
        logger.warning("Invalid OTP attempt for user_id=%s otp_id=%s purpose=%s", user.id, otp.id, purpose)
        return None, "Invalid OTP.", "invalid"

    otp.is_verified = True
    otp.verified_at = timezone.now()
    otp.save(update_fields=["is_verified", "verified_at"])
    logger.info("OTP verified for user_id=%s otp_id=%s purpose=%s", user.id, otp.id, purpose)
    return otp, "OTP verified successfully.", None


def get_verified_otp(user, purpose: str):
    return OTP.objects.filter(
        user=user,
        purpose=purpose,
        is_verified=True,
        is_used=False,
        expires_at__gt=timezone.now(),
    ).order_by(
        "-verified_at", "-created_at"
    ).first()


def mark_otp_used(otp: OTP):
    otp.is_used = True
    otp.save(update_fields=["is_used"])