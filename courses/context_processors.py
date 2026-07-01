from pathlib import Path
from urllib.parse import quote

from django.conf import settings

from enrollments.models import Enrollment


BASE_DIR = Path(__file__).resolve().parent.parent


def _read_local_env_value(key: str) -> str:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return ""

    value = ""
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        current_key, current_value = line.split("=", 1)
        if current_key.strip() != key:
            continue

        value = current_value.strip().strip('"').strip("'")

    return value


def cart_count(request):
    if not request.user.is_authenticated:
        return {"cart_count": 0}

    course_ids = request.session.get("course_cart", [])
    if not course_ids:
        return {"cart_count": 0}

    enrolled_course_ids = set(
        Enrollment.objects.filter(user=request.user, course_id__in=course_ids).values_list("course_id", flat=True)
    )
    active_course_ids = [course_id for course_id in course_ids if course_id not in enrolled_course_ids]
    return {"cart_count": len(active_course_ids)}


def support_contact(request):
    raw_number = _read_local_env_value("WHATSAPP_ADMIN_NUMBER") or getattr(settings, "WHATSAPP_ADMIN_NUMBER", "")
    support_message = _read_local_env_value("WHATSAPP_SUPPORT_MESSAGE") or getattr(settings, "WHATSAPP_SUPPORT_MESSAGE", "")

    number = "".join(character for character in str(raw_number) if character.isdigit())
    if not number:
        return {"whatsapp_support_link": "", "whatsapp_support_number": ""}

    message = support_message.strip() or "Halo Admin SkillForge, saya mengalami error di dashboard."
    whatsapp_link = f"https://wa.me/{number}?text={quote(message)}"
    return {
        "whatsapp_support_link": whatsapp_link,
        "whatsapp_support_number": number,
    }
