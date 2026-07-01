# Generated migration - Remove RedeemCode model and update Course

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0002_course_youtube_url'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.DeleteModel(
            name='RedeemCode',
        ),
        migrations.RemoveField(
            model_name='course',
            name='is_paid',
        ),
        migrations.RemoveField(
            model_name='course',
            name='price',
        ),
        migrations.AlterField(
            model_name='course',
            name='instructor',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='courses', to=settings.AUTH_USER_MODEL),
        ),
    ]
