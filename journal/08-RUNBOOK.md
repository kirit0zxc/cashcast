# Полная проверка Chronos и специалистов

Использовать отдельную локальную копию CashCast `a92bd5013b5b5d7e5008157815160b67fd762edf`.
Приложение, БД, фронтенд и production этот эксперимент не меняет. Все команды из
корня `work/cashcast-model-fallback`. Настройка сред и скачивание закреплённых весов
Chronos описаны в [ROUND2-RUNBOOK.md](ROUND2-RUNBOOK.md), версии — ENVIRONMENTS.json.

```powershell
$datasetZip = '../../outputs/cashcast-datasets-2026-10-24/01-organizers/cashflow_dataset_participants.zip'
$runDir = 'data/raw/chronos-specialists-repeat'

# 1. Сверенные окна, текущий прогноз, ранее обученный CatBoost и прошлые контексты.
& '../cashcast-eval-env/Scripts/python.exe' experiments/08_chronos_specialists.py `
 --stage prepare --zip $datasetZip `
 --weights data/raw/fallback-model-v1/direct_depth6.cbm --output $runDir

# 2. Только локальные веса: исходные операции никуда не передаются.
$env:HF_HUB_OFFLINE='1'
$env:HF_HUB_DISABLE_PROGRESS_BARS='1'
& '../cashcast-chronos-env/Scripts/python.exe' experiments/08_chronos_specialists.py `
 --stage infer --model-info journal/chronos-source.json --output $runDir

# 3. Выбор по ранним срезам, затем расчёт всех метрик.
& '../cashcast-eval-env/Scripts/python.exe' experiments/08_chronos_specialists.py `
 --stage score --output $runDir

# 4. Чистые локальные проверки, не нужна тестовая БД.
& '../cashcast-eval-env/Scripts/python.exe' -m unittest `
 evaluation.fallback_model.test_model evaluation.liquidity_risk.test_risk `
 evaluation.liquidity_risk.test_extensions evaluation.liquidity_risk.test_final `
 evaluation.liquidity_risk.test_specialists -v
```

`results.json` содержит горизонты 7/14/30, MAE/MSE/RMSE и macro-MAE, ошибки потоков
и сумм, покрытие/ширину/pinball интервалов, матрицы разрывов, ROC-AUC/AP ранжирующего
score Chronos и сравнение с текущим score на одинаковых окнах. Score Chronos не является
вероятностью, Brier к нему не применяется. Состав специалистов хранится в
`selection-frozen.json`, политика тревог — `risk-selection-frozen.json`.

Ранние даты других компаний не используются для подбора. При этом весь текущий
набор уже изучался, поэтому результаты не называются слепым контрольным тестом.
Под «полной проверкой» здесь понимаются все пригодные месячные срезы января—августа
2026 по всем 150 компаниям, а не все возможные даты или гарантия универсальной точности.
Chronos не дообучается в этом эксперименте.

Промежуточные pickle содержат строки счетов и прогнозов. Они созданы локально самим
экспериментом, не включаются в архив и не предназначены для загрузки от посторонних.
Нельзя передавать этому скрипту чужой pickle. Новый запуск сохранять в отдельный каталог.

Специалистская сборка — исследовательская: полноценное подключение к API потребует
отдельно согласовать семантику графика, денежных потоков, планов/сценариев и источников
риска. Автоматического выпуска в рабочий сайт в этом пакете нет.
