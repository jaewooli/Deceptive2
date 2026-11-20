# moayeyak-web

모아예약 웹 서비스 (Flask + gunicorn, nginx 뒤).

## 실행

예약 확인서 PDF: `sudo apt install weasyprint fonts-nanum`

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
set -a; . ./.env; set +a      # .env.example 참고
.venv/bin/flask --app wsgi init-db
.venv/bin/flask --app wsgi create-admin <id>
.venv/bin/gunicorn -b 127.0.0.1:8000 wsgi:app
```

## 배포 (web-01)

- 코드: `/srv/app` (`deploy` 계정)
- 설정: `/srv/app/.env` → `deploy/moayeyak.service`의 EnvironmentFile
- nginx: `deploy/nginx-moayeyak.conf` → `/etc/nginx/sites-available/moayeyak`
