from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_remove_instructorapplication_and_user_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="profile_image",
            field=models.ImageField(blank=True, null=True, upload_to="profiles/"),
        ),
    ]
