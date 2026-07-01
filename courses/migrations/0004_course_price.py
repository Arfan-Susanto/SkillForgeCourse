from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0003_remove_redeem_code_and_pricing"),
    ]

    operations = [
        migrations.AddField(
            model_name="course",
            name="price",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
    ]
