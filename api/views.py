from rest_framework import mixins, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.http import HttpResponse
from requests import RequestException
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.db import OperationalError

from courses.models import Course
from enrollments.models import Enrollment

from .serializers import (
    CourseSerializer,
    EnrollmentSerializer,
    LoginSerializer,
    RegisterSerializer,
    SupportChatSerializer,
    SupportKnowledgeDocumentSerializer,
    UserSerializer,
)
from .models import SupportKnowledgeDocument
from .support_rag import (
    build_support_prompt,
    build_support_fallback_answer,
    call_support_chat,
    get_support_rag_status,
    is_support_rag_enabled,
    retrieve_knowledge_context,
)


class RegisterAPI(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"user": UserSerializer(user).data, "token": token.key}, status=status.HTTP_201_CREATED)


class LoginAPI(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": UserSerializer(user).data})


class LogoutAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response({"detail": "Logged out successfully."})


class MeAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class CourseViewSet(viewsets.ModelViewSet):
    queryset = Course.objects.select_related("instructor").all()
    serializer_class = CourseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        q = self.request.query_params.get("q", "").strip()
        if q:
            queryset = queryset.filter(title__icontains=q)
        return queryset


class EnrollmentViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = EnrollmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Enrollment.objects.filter(user=self.request.user).select_related("user", "course")


class SupportKnowledgeDocumentViewSet(viewsets.ModelViewSet):
    queryset = SupportKnowledgeDocument.objects.all()
    serializer_class = SupportKnowledgeDocumentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        is_active = self.request.query_params.get("is_active")
        if is_active in {"true", "false"}:
            queryset = queryset.filter(is_active=(is_active == "true"))
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def _ensure_staff(self, request):
        if not request.user.is_staff:
            return Response({"detail": "Hanya admin/staff yang boleh mengelola knowledge base."}, status=status.HTTP_403_FORBIDDEN)
        return None

    def create(self, request, *args, **kwargs):
        denied = self._ensure_staff(request)
        if denied:
            return denied
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        denied = self._ensure_staff(request)
        if denied:
            return denied
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        denied = self._ensure_staff(request)
        if denied:
            return denied
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        denied = self._ensure_staff(request)
        if denied:
            return denied
        return super().destroy(request, *args, **kwargs)


@method_decorator(csrf_exempt, name="dispatch")
class SupportChatAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SupportChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        enabled, reason = get_support_rag_status()
        if not enabled:
            return Response(
                {
                    "detail": "Fitur support chat RAG dinonaktifkan pada deployment ini.",
                    "reason": reason,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        user_message = serializer.validated_data["message"]

        try:
            context_chunks = retrieve_knowledge_context(user_message)
        except OperationalError:
            context_chunks = []
        except Exception:
            context_chunks = []

        system_prompt = "Anda adalah asisten customer service untuk platform SkillForge."
        history_messages = serializer.validated_data.get("history", [])
        user_prompt = build_support_prompt(
            context_chunks=context_chunks,
            user_message=user_message,
            history_messages=history_messages,
        )

        sources = [
            {
                "title": chunk["title"],
                "source_url": chunk.get("source_url", ""),
                "chunk_index": chunk["chunk_index"],
            }
            for chunk in context_chunks
        ]

        request._support_chat_sources = sources
        request._support_chat_context_count = len(context_chunks)

        try:
            answer = call_support_chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                history_messages=history_messages,
            )
        except RequestException as exc:
            request._support_chat_fallback_used = True
            request._support_chat_fallback_reason = str(exc)
            fallback_answer = build_support_fallback_answer(context_chunks, user_message)
            return HttpResponse(fallback_answer, content_type="text/plain; charset=utf-8")
        except RuntimeError as exc:
            detail = str(exc) or "Gagal memproses respons AI."
            normalized_detail = detail.lower()
            request._support_chat_fallback_used = True
            request._support_chat_fallback_reason = detail

            if any(keyword in normalized_detail for keyword in ["quota", "rate-limit", "rate limit", "too many requests", "resource exhausted"]):
                fallback_answer = build_support_fallback_answer(context_chunks, user_message)
                return HttpResponse(fallback_answer, content_type="text/plain; charset=utf-8")

            fallback_answer = build_support_fallback_answer(context_chunks, user_message)
            return HttpResponse(fallback_answer, content_type="text/plain; charset=utf-8")
        except Exception as exc:
            request._support_chat_fallback_used = True
            request._support_chat_fallback_reason = str(exc)
            fallback_answer = build_support_fallback_answer(context_chunks, user_message)
            return HttpResponse(fallback_answer, content_type="text/plain; charset=utf-8")
        request._support_chat_fallback_used = False
        return HttpResponse(answer, content_type="text/plain; charset=utf-8")
