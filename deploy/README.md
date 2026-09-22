# Развёртывание neftecode.goatwhistle.ru

Сервер Ubuntu запускает `neftecode serve` под отдельным пользователем. Caddy
проксирует запросы и автоматически получает сертификат HTTPS. Для чистого клона
используются синтетические сценарии; исторические срезы и обученная модель в Git
не включены.

```sh
# На сервере, после доставки репозитория в /srv/neftecode:
useradd --system --home /srv/neftecode --shell /usr/sbin/nologin neftecode
mkdir -p /srv/neftecode/artifacts
chown neftecode:neftecode /srv/neftecode/artifacts
cd /srv/neftecode
export UV_PYTHON_INSTALL_DIR=/opt/uv/python
uv python install 3.12
uv sync --frozen --no-dev --python 3.12
install -m 0644 deploy/neftecode.service /etc/systemd/system/neftecode.service
install -m 0644 deploy/Caddyfile /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable --now neftecode caddy
```

Нужны `uv` и `caddy`, а DNS-запись A домена должна указывать на сервер.
Порты 80 и 443 должны быть доступны для автоматического получения сертификата.
Проверка: `curl -fsS https://neftecode.goatwhistle.ru/api/scenarios`.

Чтобы включить другого LLM-провайдера, укажите настройки в `/etc/neftecode.env`
с правами root и перезапустите `neftecode`. По умолчанию агентный слой отключён,
расчёт не требует внешнего API.
