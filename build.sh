#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
python manage.py shell -c "
from django.contrib.auth.models import User
if not User.objects.filter(username='superadmin').exists():
    u = User.objects.create_superuser('superadmin', 'testphdguy@gmail.com', 'MoviesNight')
    print('Admin created')
else:
    print('Admin already exists, skipping')
"