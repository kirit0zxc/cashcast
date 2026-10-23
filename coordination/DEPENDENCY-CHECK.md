# Проверка frontend-зависимостей · ночь24.10.2026

Исходный checkpoint777ff22: npm audit сообщил4группы (2low/1moderate/1high):
ESLint/plugin-kit и Vite/esbuild. Это инструменты разработки и сборки; production
nginx-образ содержит только dist и nginx.conf, не Node/dev-server.

Вместо audit fix --force выбраны конкретные совместимые версии:

| Зависимость | До | После |
|---|---|---|
| Vite |5.4.11|6.4.4|
| ESLint и @eslint/js |9.15.0|9.39.5|
| esbuild, транзитивная dev |0.21.5|0.25.12|
| plugin-kit, транзитивная dev |0.2.8|0.4.1|

React, TypeScript, Recharts, Playwright, plugin-react и runtime dependencies не
менялись. Registry peerDependencies существующего plugin-react4.3.4 включают Vite6;
Node24 удовлетворяет engines. Lock закрепляет версии/integrity; все изменённые
package entries помечены dev. Vite6 — смена major, поэтому одного audit недостаточно.
Проект не использует SSR, Sass, library-mode или custom resolve.conditions.

Проверенные первичные сведения: [релиз6.4.4](https://github.com/vitejs/vite/releases/tag/v6.4.4),
[переход5→6](https://v6.vite.dev/guide/migration),
[advisory esbuild](https://github.com/evanw/esbuild/security/advisories/GHSA-67mh-4wv8-2f99).
Изменение конфигурации приложения для совместимости не потребовалось.

После установки npm сообщил0известных уязвимостей, lint/typecheck/4unit/build прошли.
Чистый Linux npm ci/Docker build и реальная браузерная приёмка фиксируются в A.md
после завершения. Результат audit относится к состоянию advisory-базы этой ночью;
он не является гарантией отсутствия неизвестных проблем или бессрочной поддержки.
Предупреждения о старых ветках/размере bundle не скрывались.

Actions новыхпакетов not_run по night-ci-quota-v1; эта проверка выполнена локально.
