# Отчёт качества v1

Владелец 24.10.2026 поручил отдельным PR отдавать полный отчёт качества через API.
`GET /api/v1/models/quality` — чтение после входа, без company_id: данные общие,
обезличенные и не зависят от клиентского счёта. Роли owner/viewer имеют одинаковый
доступ. Без сессии 401; при повреждённом снимке 503 quality_report_unavailable.
Запись, обучение и обращение к raw-данным по HTTP не выполняются.

`scope=offline_external_evaluation`, `evaluated_model` и
`applies_to_current_forecast=false` обязательны: это измерения исследовательского
CatBoost, а не текущего seasonal-guarded прогноза пользователя. Модель не включается
этим endpoint. `production_activated=false`, `probability_calibrated=false`.

В cohorts представлены validation, test_development_accounts и test_unseen_accounts:
число окон, счетов и положительных примеров, порог, TP/FP/FN/TN, precision, recall,
F1/F2, specificity, FPR, accuracy, balanced accuracy, MCC, prevalence, ROC-AUC,
average precision (не трапецеидальная PR-AUC), Brier и Brier постоянного baseline.
Каждая метрика имеет value, definition и unavailable_reason; неопределённое значение
равно null, а не нулю. Accuracy нельзя трактовать как достаточный критерий для редких
разрывов. Uncertainty сохраняет опубликованные bootstrap-интервалы и число валидных
повторов; интервалы не вычислены для всех метрик.

Evidence содержит полные исходные агрегаты с путём и SHA256: Berka, дополнительную
калибровку/пороги/интервалы и MoneyVis. SHA256 использует `hash_format=utf8_lf`:
переносы строк нормализованы к LF для одинаковой проверки на Linux и Windows.
Для MoneyVis доступны MAE притока/оттока/остатка,
ошибка конечного остатка, сравнение трёх моделей на горизонтах 7/14/30 дней. Это единицы
исходной валюты, не рубли. ROC-AUC на этом счёте null из-за отсутствия положительного
класса. Синтетические результаты и метрики действующей модели не подменяются этими
измерениями. Release и limitations обязательны; 1998 — уже просмотренная ретроспектива.

Снимок включён в backend/app и автоматически попадает в Docker-образ. Обновление:
`python -m evaluation.export_quality` из корня. Тест сравнивает снимок со всеми
исходными агрегатами и их хэшами; ручные исправления чисел не допускаются.

## Проверка

1. Войти в обычный кабинет.
2. На том же адресе открыть `/api/v1/models/quality` (через proxy веб-приложения).
3. Проверить `test_unseen_accounts`: TP=6, FP=14, FN=5, TN=3148, precision=0.3,
   recall≈0.54545, F1≈0.38710; это сохранённый эксперимент, не обещание будущей точности.
4. Посмотреть evidence для таблиц MoneyVis и selection_policy для всех проверенных
   порогов. selected=null и release.allowed=false — критерии выпуска не пройдены.
5. Выйти из кабинета: тот же запрос возвращает 401.

Ответ можно сохранить как JSON для презентации. OpenAPI: specs/openapi.json.
