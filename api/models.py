from django.conf import settings
from django.db import models


class SupportKnowledgeDocument(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    source_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_docs_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["is_active", "updated_at"])]

    def __str__(self):
        return self.title
