# Локальное дообучение Chronos

Запуск из отдельной исследовательской копии `cashcast-model-fallback`.
Нужны установленное соседнее `cashcast-chronos-env`, локальный checkpoint из
`chronos-source.json` и оригинальный ZIP организаторов. Проверка SHA ZIP обязательна.
Сайт, API и БД не используются. Веса сохраняются на диске; не публиковать данные.

```powershell
$env:HF_HUB_OFFLINE='1'
$env:HF_HUB_DISABLE_PROGRESS_BARS='1'
$env:PYTHONIOENCODING='utf-8'
$chronosPython='../cashcast-chronos-env/Scripts/python.exe'
$sourceZip='../../outputs/cashcast-datasets-2026-10-24/01-organizers/cashflow_dataset_participants.zip'

# Для повторения нужен новый каталог. Не запускайте вторую копию живого обучения.
& $chronosPython experiments/13_chronos_finetune.py --zip $sourceZip --output data/raw/chronos-finetune-repeat

# Сначала январь—июнь и заморозка выбора, только затем остальные фазы.
& $chronosPython -m evaluation.liquidity_risk.finetune_evaluate --training data/raw/chronos-finetune-repeat --output data/raw/chronos-finetune-repeat/evaluation
```

Оценка использует собственный проверенный кэш эксперимента08:
`data/raw/chronos-specialists-v8`. Его исходные окна/даты идентичны сравнению
с текущей моделью и 75%Chronos+25%CatBoost. При переносе сначала воспроизвести08
по его инструкции. Не загружать pickle из неизвестного источника.

В обучающем каталоге: manifest рядов и хешей, исходные хеши модели, checkpoints
100/200/300, финальный checkpoint и подтверждение конечного выхода/неизменности
исходных весов. Checkpoint200 не участвует в выборе. В evaluation сохраняются
замороженный выбор, все метрики и предсказания каждого окна. Повтор тех же данных
не считается новым независимым тестом. Переобучение не гарантирует улучшения.

Риск здесь — сигнал пересечения нуля нижним дневным квантилем, а не калиброванная
вероятность минуса в течение месяца. Для рабочей вероятности требуется отдельная
валидация. Исследовательский кандидат не включается на сайте автоматически.
