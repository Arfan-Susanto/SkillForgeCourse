from django.core.management.base import BaseCommand

from api.support_rag import sync_support_knowledge_to_qdrant


class Command(BaseCommand):
    help = "Sync active support knowledge base chunks to Qdrant."

    def handle(self, *args, **options):
        synced = sync_support_knowledge_to_qdrant(force=True)
        if synced:
            self.stdout.write(self.style.SUCCESS(f"Synced {synced} chunks to Qdrant."))
        else:
            self.stdout.write(self.style.WARNING("No chunks synced. Check Qdrant connection, embedding model, or knowledge base contents."))