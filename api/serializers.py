from django.contrib.auth import authenticate
from rest_framework import serializers

from accounts.models import User
from courses.models import Course
from enrollments.models import Enrollment
from .models import SupportKnowledgeDocument


MAX_THUMBNAIL_SIZE = 2 * 1024 * 1024  # 2 MB
ALLOWED_IMAGE_FORMATS = ("JPEG", "PNG", "WEBP")


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "password"]

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(username=attrs.get("username"), password=attrs.get("password"))
        if not user:
            raise serializers.ValidationError("Invalid credentials.")
        attrs["user"] = user
        return attrs


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email"]


class CourseSerializer(serializers.ModelSerializer):
    enrolled_students_count = serializers.IntegerField(read_only=True)
    youtube_embed_url = serializers.CharField(read_only=True)

    def validate_thumbnail(self, value):
        # Validate file size
        if getattr(value, "size", 0) > MAX_THUMBNAIL_SIZE:
            raise serializers.ValidationError("Thumbnail terlalu besar (maks 2MB).")

        # Verify image contents using Pillow
        try:
            from PIL import Image, UnidentifiedImageError

            # Pillow expects a file-like object; ensure we can read/seek
            value.seek(0)
            img = Image.open(value)
            img.verify()
            fmt = getattr(img, "format", None)
            if fmt and fmt.upper() not in ALLOWED_IMAGE_FORMATS:
                raise serializers.ValidationError("Format gambar tidak didukung (boleh: JPEG, PNG, WEBP).")
        except ImportError:
            # Pillow not installed — fail safe by rejecting unknown content
            raise serializers.ValidationError("Server tidak mendukung pemeriksaan gambar. Hubungi admin.")
        except UnidentifiedImageError:
            raise serializers.ValidationError("File yang diunggah bukan gambar yang valid.")
        finally:
            try:
                value.seek(0)
            except Exception:
                pass

        return value

    class Meta:
        model = Course
        fields = [
            "id",
            "title",
            "description",
            "youtube_url",
            "youtube_embed_url",
            "thumbnail",
            "enrolled_students_count",
            "created_at",
            "updated_at",
        ]


class EnrollmentSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    course = CourseSerializer(read_only=True)

    class Meta:
        model = Enrollment
        fields = ["id", "user", "course", "granted_via", "amount_paid", "created_at"]


class SupportKnowledgeDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportKnowledgeDocument
        fields = ["id", "title", "content", "source_url", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class SupportChatHistoryMessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["user", "assistant"])
    content = serializers.CharField(max_length=2000, trim_whitespace=True)


class SupportChatSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=2000)
    history = SupportChatHistoryMessageSerializer(many=True, required=False, default=list)
