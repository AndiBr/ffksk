# -*- coding: utf-8 -*-
# Generated by Django 1.11 on 2018-06-17 23:47
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('profil', '0007_kioskuser_activity_end_msg'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='kioskuser',
            name='positionFfE',
        ),
        migrations.AddField(
            model_name='kioskuser',
            name='dsgvo_accepted',
            field=models.BooleanField(default=False),
        ),
    ]
