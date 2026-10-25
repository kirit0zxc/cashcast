# SR04: развёртывание, диагностика и откат

Используйте основной Compose и `infra/compose.risk-ml.yml` из одного коммита.
Архив модели уже включён в Git; загрузка из личных Downloads больше не нужна.
Для чистого запуска выполните команды README. Исходные веса и правила флага совпадают
с демонстрационным стендом 25.10.2026. Пароли, hostname, TLS и существующая БД не входят в репозиторий.

## Публичный Linux-сервер

1. Установите Docker с Compose v2, клонируйте main в отдельный каталог.
2. Создайте `infra/.env` из примера. Сгенерируйте собственные `POSTGRES_PASSWORD` и
   `CC_DEMO_PASSWORD`, задайте `CC_DEMO_EMAIL`. Пароль БД в `CC_DATABASE_URL` должен
   совпадать с `POSTGRES_PASSWORD` и быть URL-encoded при наличии специальных символов.
3. Поставьте `CC_APP_ENV=prod`, `CC_COOKIE_SECURE=true`. Доступ к `.env` ограничьте владельцем.
4. Перед существующими данными сохраните дамп PostgreSQL, файл env и SHA текущего релиза.
   Дамп содержит финансовые данные: храните его закрыто, не в Git. Не меняйте пароль
   уже инициализированной БД только через env — это не обновит роль в PostgreSQL.
5. Запустите оба Compose-файла командой из README. `migrate` автоматически применяет
   миграции; в самом изменении SR04 новых миграций нет. Используйте постоянное имя
   Compose project (`-p cashcast`), чтобы обновление каталога не создало другую БД.
6. Настройте домен на сервер и HTTPS reverse proxy к `127.0.0.1:8080`.
   Например, Caddy на хосте с публичным DNS:

```caddyfile
cashcast.example.org {
    reverse_proxy 127.0.0.1:8080
}
```

Замените домен своим; сертификат требует доступных 80/443 и корректного DNS.
Не публикуйте наружу 5432, 8000 и 8765. Cookie Secure требует входа именно по HTTPS.
Внешний proxy должен корректно передавать Host и X-Forwarded-Proto. Перед открытием
доступа проверьте login, импорт и получение прогноза через публичный адрес.

## Проверка

```bash
docker compose --env-file infra/.env -f infra/docker-compose.yml -f infra/compose.risk-ml.yml ps -a
docker compose --env-file infra/.env -f infra/docker-compose.yml -f infra/compose.risk-ml.yml exec -T risk-ml python /app/smoke.py
curl --fail http://127.0.0.1:8080/api/v1/health
```

В кабинете новый флаг находится под денежными показателями «Обзора» и в «Прогнозе».
В API это `risk.ml_flag`. `available=true` требует boolean `flag`. `null` — не «нет».
Процент основного прогноза находится в прежнем `risk.probability_any_negative`.

«Не оценено» на коротком демонаборе — ожидаемо. Требуются 84 дня согласованной истории,
подтверждённые операцией/остатком календарные дни, неотрицательный текущий остаток и 30-дневный горизонт.
После изменения фактов запустите новый прогноз: старый использует собственный frozen snapshot.
Планы не входят в SR04; при открытии сценария флаг недоступен.

`model_unavailable`: проверьте health контейнера, связь API → `risk-ml:8765` и его логи
(`logs --tail 50 risk-ml`). Не публикуйте тела выписок и env при передаче диагностики.
Ошибка хеша при сборке означает, что пакет отличается от закреплённого; не отключайте проверку.

## Отключение и откат

Чтобы отключить дополнительный флаг, сохранив прогноз и данные, пересоздайте API
без ML override (те же env, базовый файл и имя Compose project):

```bash
docker compose --env-file infra/.env -f infra/docker-compose.yml up -d --no-deps --force-recreate api
docker compose --env-file infra/.env -f infra/docker-compose.yml -f infra/compose.risk-ml.yml stop risk-ml
```

После обновления страницы `ml_flag` будет null и блок скроется. Полный откат приложения:
предыдущий проверенный commit/images с тем же env и volume; не выполняйте `down -v`.
На существующем сервере учитывайте дополнительные production override-файлы — не
заменяйте его wrapper локальной командой с потерей TLS/логирования/портов.
