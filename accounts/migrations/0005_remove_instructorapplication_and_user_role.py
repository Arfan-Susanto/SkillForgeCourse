# Generated migration - Remove InstructorApplication model and role field

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_instructor_application'),
    ]

    operations = [
        migrations.DeleteModel(
            name='InstructorApplication',
        ),
        migrations.RemoveField(
            model_name='user',
            name='role',
        ),
    ]
