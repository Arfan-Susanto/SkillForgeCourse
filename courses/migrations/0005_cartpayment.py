from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0004_course_price"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CartPayment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("order_id", models.CharField(max_length=80, unique=True)),
                ("course_ids", models.JSONField(blank=True, default=list)),
                ("gross_amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("settlement", "Settlement"), ("capture", "Capture"), ("deny", "Deny"), ("expire", "Expire"), ("cancel", "Cancel"), ("error", "Error")], default="pending", max_length=20)),
                ("snap_token", models.CharField(blank=True, max_length=255)),
                ("transaction_id", models.CharField(blank=True, max_length=100)),
                ("payment_type", models.CharField(blank=True, max_length=50)),
                ("raw_response", models.JSONField(blank=True, default=dict, null=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cart_payments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]