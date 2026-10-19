# DEPLOY.md — 통합 상담 어드민 배포 (Cafe24 가상서버)

서버: 211.45.175.195 (root, MobaXterm). nginx 80/443, 앱은 gunicorn 로컬 포트. DB MariaDB localhost:3306.
아래 블록을 순서대로 붙여넣는다. `PORT`는 **8047** (8045 gallery, 8046 rawsRn 사용 중).

## 블록 1 — 포트 확인 · 코드 · venv · .env · systemd

```bash
ss -tlnp | grep ':8047 ' && echo "!! 8047 사용중" || echo "8047 비어있음 OK"
timedatectl set-timezone Asia/Seoul

cd /var/www && git clone https://github.com/Jeongdonghwan/inquiry-admin.git inquiry-admin && cd inquiry-admin
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt

cp .env.example .env
sed -i "s|^FLASK_ENV=.*|FLASK_ENV=production|" .env
sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$(openssl rand -hex 24)|" .env
sed -i "s|^DATABASE_URL=.*|DATABASE_URL=mysql+pymysql://inquiry_admin:1234@localhost:3306/inquiry_admin?charset=utf8mb4|" .env
sed -i "s|^ADMIN_BASE_URL=.*|ADMIN_BASE_URL=http://211.45.175.195:8047|" .env
sed -i "s|^COMPANY_NAME=.*|COMPANY_NAME=법률사무소 알엠|" .env
sed -i "s|^REPRESENTATIVE_PHONE=.*|REPRESENTATIVE_PHONE=031-000-0000|" .env
cat .env

cat > /etc/systemd/system/inquiry-admin.service <<'EOF'
[Unit]
Description=inquiry-admin Flask (gunicorn :8047)
After=network.target mariadb.service

[Service]
WorkingDirectory=/var/www/inquiry-admin
EnvironmentFile=/var/www/inquiry-admin/.env
Environment=FLASK_APP=wsgi.py
ExecStart=/var/www/inquiry-admin/venv/bin/gunicorn -w 2 --threads 2 -b 127.0.0.1:8047 wsgi:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
```

## 블록 2 — DB (root 비밀번호 입력)

```bash
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS inquiry_admin CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; CREATE USER IF NOT EXISTS 'inquiry_admin'@'localhost'; ALTER USER 'inquiry_admin'@'localhost' IDENTIFIED BY '1234'; GRANT ALL PRIVILEGES ON inquiry_admin.* TO 'inquiry_admin'@'localhost'; FLUSH PRIVILEGES;"
cd /var/www/inquiry-admin && set -a && . ./.env && set +a && FLASK_APP=wsgi.py ./venv/bin/flask db upgrade
FLASK_APP=wsgi.py ./venv/bin/flask create-admin admin 'CHANGE-ME-NOW' --name 관리자
```

운영 DB에는 `flask seed`를 실행하지 않는다(코드가 거부함). 사이트·직원은 어드민 화면에서 등록.

## 블록 3 — 기동 · nginx 임시 공개 · crontab

```bash
systemctl enable --now inquiry-admin && systemctl status inquiry-admin --no-pager
curl -s -o /dev/null -w "login:%{http_code}\n" http://127.0.0.1:8047/login

# 도메인 전까지 임시 공개 (SSL 없이 공인망 노출 — 도메인 붙인 뒤 반드시 닫을 것)
cat > /etc/nginx/sites-available/inquiry-admin-tmp <<'EOF'
server { listen 8147; location / { proxy_pass http://127.0.0.1:8047; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto $scheme; } }
EOF
ln -sf /etc/nginx/sites-available/inquiry-admin-tmp /etc/nginx/sites-enabled/ && nginx -t && systemctl reload nginx
ufw status | head -1   # active 면: ufw allow 8147/tcp

( crontab -l 2>/dev/null; cat <<'EOF'
* * * * *  cd /var/www/inquiry-admin && set -a && . ./.env && set +a && FLASK_APP=wsgi.py ./venv/bin/flask sms-worker >> /var/log/inquiry-sms.log 2>&1
0 4 * * *  cd /var/www/inquiry-admin && set -a && . ./.env && set +a && FLASK_APP=wsgi.py ./venv/bin/flask privacy-sweep >> /var/log/inquiry-privacy.log 2>&1
30 4 * * * mysqldump -u inquiry_admin -p1234 inquiry_admin | gzip > /var/backups/inquiry_admin_$(date +\%Y\%m\%d).sql.gz && find /var/backups -name 'inquiry_admin_*.gz' -mtime +14 -delete
EOF
) | crontab -
crontab -l
```

접속: `http://211.45.175.195:8147/login` (admin / 블록 2에서 정한 비밀번호)

## 도메인 연결 (예: admin.example.co.kr)

```bash
dig +short admin.example.co.kr   # 211.45.175.195 나와야 함
cat > /etc/nginx/sites-available/inquiry-admin <<'EOF'
server {
    listen 80;
    server_name admin.example.co.kr;
    client_max_body_size 10M;
    location / {
        proxy_pass http://127.0.0.1:8047;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF
ln -sf /etc/nginx/sites-available/inquiry-admin /etc/nginx/sites-enabled/ && rm -f /etc/nginx/sites-enabled/inquiry-admin-tmp
nginx -t && systemctl reload nginx
certbot --nginx -d admin.example.co.kr --agree-tos -m 메일주소 --redirect -n
cd /var/www/inquiry-admin && sed -i "s|^ADMIN_BASE_URL=.*|ADMIN_BASE_URL=https://admin.example.co.kr|" .env && systemctl restart inquiry-admin
ufw delete allow 8147/tcp 2>/dev/null
```

운영은 HTTPS 필수(세션 쿠키 `Secure`). `FLASK_ENV=production`이면 쿠키에 Secure가 붙으므로 **HTTPS 전에는 로그인이 유지되지 않는다** — 임시 공개 기간에만 `FLASK_ENV=development`로 두고, 도메인·SSL 후 production으로 바꾼다.

## 업데이트

```bash
cd /var/www/inquiry-admin && git pull && ./venv/bin/pip install -r requirements.txt -q && set -a && . ./.env && set +a && FLASK_APP=wsgi.py ./venv/bin/flask db upgrade && systemctl restart inquiry-admin && systemctl status inquiry-admin --no-pager
```

## 문자(알리고) 켜기

`.env`에 `SMS_PROVIDER=aligo`, `ALIGO_API_KEY`, `ALIGO_USER_ID`, 발신번호(사전 등록) 입력 → `ALIGO_TESTMODE=Y`로 1건 확인 → `N`으로 전환 → `systemctl restart inquiry-admin`.

## 사이트 연결 (법률사무소 알엠 등)

어드민 > 사이트·폼 연동 > 사이트 추가 → 비밀키를 해당 사이트 서버 `.env`의 `SITE_SECRET`, 어드민 주소를 `HUB_URL`에 넣고 재시작. 각 홈페이지에 개인정보처리방침(수집 항목·보관기간·위탁: 문자발송사) 게시.
