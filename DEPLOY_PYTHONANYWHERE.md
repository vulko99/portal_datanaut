# Deploying DataNaut on PythonAnywhere (free tier)

These steps publish the site at `https://<username>.pythonanywhere.com`.
Replace `<username>` with your PythonAnywhere username throughout.

## 1. Get the code
Open a **Bash console** (Consoles tab) and clone the branch:

```bash
git clone -b claude/upbeat-lamport-u6zth8 https://github.com/vulko99/portal_datanaut.git
cd portal_datanaut
```

## 2. Virtualenv + dependencies

```bash
python3.11 -m venv ~/venv
source ~/venv/bin/activate
pip install -r requirements.txt reportlab openpyxl
```

## 3. Database + static files

```bash
cp db.sqlite3.bak db.sqlite3      # the repo ships a backup, not db.sqlite3
python manage.py migrate
python manage.py collectstatic --noinput
```

## 4. Create the web app
**Web** tab → *Add a new web app* → **Manual configuration** → **Python 3.11**.

- **Virtualenv**: set it to `/home/<username>/venv`
- **Source code / Working directory**: `/home/<username>/portal_datanaut`

## 5. Edit the WSGI file
In the Web tab, click the **WSGI configuration file** link and replace its
contents with:

```python
import os
import sys

path = "/home/<username>/portal_datanaut"
if path not in sys.path:
    sys.path.insert(0, path)

os.environ["DJANGO_SETTINGS_MODULE"] = "datanaut_site.settings"
os.environ["PYTHONANYWHERE_HOST"] = "<username>.pythonanywhere.com"
os.environ["DJANGO_DEBUG"] = "False"
# Optional but recommended – generate one with:
#   python -c "import secrets; print(secrets.token_urlsafe(50))"
# os.environ["DJANGO_SECRET_KEY"] = "paste-a-long-random-value"

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

`PYTHONANYWHERE_HOST` is read by `settings.py` and added to both
`ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`, so logins and the contact form work.

## 6. Map static files
Web tab → **Static files** section → add:

| URL | Directory |
|-----|-----------|
| `/static/` | `/home/<username>/portal_datanaut/staticfiles` |

(With `DEBUG=False`, Django does not serve static files itself — this mapping
does, which is why step 3 ran `collectstatic`.)

## 7. Reload
Click the green **Reload** button, then open
`https://<username>.pythonanywhere.com/`. It redirects to `/en/`; try `/bg/`
and `/de/` for the translations and `/demo/` for the platform page.

## Updating later
After pushing new commits:

```bash
cd ~/portal_datanaut && git pull
source ~/venv/bin/activate
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py compilemessages   # only if translations changed
```

Then hit **Reload** in the Web tab.
