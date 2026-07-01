from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_otp_and_email_constraint"),
    ]

    operations = [
        migrations.AddField(
            model_name="otp",
            name="purpose",
            field=models.CharField(
                choices=[("login", "Login"), ("password_reset", "Password Reset")],
                default="password_reset",
                max_length=20,
            ),
        ),
        migrations.RemoveIndex(
            model_name="otp",
            name="accounts_otp_user_8e2d1e_idx",
        ),
        migrations.AddIndex(
            model_name="otp",
            index=models.Index(
                fields=["user", "purpose", "is_used", "is_verified", "expires_at"],
                name="accounts_otp_user_3e0f89_idx",
            ),
        ),
    ]