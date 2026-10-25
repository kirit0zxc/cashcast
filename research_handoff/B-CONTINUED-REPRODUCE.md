# Воспроизведение продолжения B

Точный source_commit/source_tree указан в bundle-manifest.json. source.zip и оба
корневых документа извлечены из этого же commit. Внешний SHA находится в receipt.json
рядом с архивом. Это промежуточная точка продолжающегося исследования.

Окружения, проверка пяти исходных архивов A и полное восстановление описаны
в B-REPRODUCE.md. Базовый SHA A: ae45cf36cea8eb9c7909436e5ac62c0f6edfb85a.
Точные зависимости и версии сохранены в requirements-*.txt и B-ENVIRONMENT-*.json.
Датасет предоставляется отдельно; SHA256:
e753802b7f7a2eecb7b5a558f9923b529e711c40fe431774750904b62ec79987.

Пакет содержит исходные18/21, дополнения25/29/31, сохранённые риск-прогнозы,
точный исходный код и агрегированные результаты. Банковские операции, обучающие
признаки и окружения не входят. Веса отвергнутых опытов и проверок устойчивости
сохранены локально, их SHA — results-continued/local-artifact-index.json.

Перед первым импортом обязательно установите PYTHONDONTWRITEBYTECODE=1:
исходный21 содержит два хешированных pyc. Не пересчитывайте manifest под изменённый
кэш. У новых дополнений pyc нет. Оригинальные ZIP18/21 не имеют верхней папки,
а ZIP25/29/31 имеют префикс cashcast-risk-addon-vN. В новом каталоге:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:HF_HUB_OFFLINE='1'
New-Item -ItemType Directory -Force data/raw/tmp | Out-Null
$env:TEMP=(Resolve-Path data/raw/tmp).Path
$env:TMP=$env:TEMP
$tab=(Resolve-Path .venv/research/Scripts/python.exe).Path
$chr=(Resolve-Path .venv/chronos/Scripts/python.exe).Path
$delivery='C:/path/to/extracted/continued-bundle'
# Для runtime-only; полный restore — альтернативный маршрут из B-REPRODUCE.md.
Expand-Archive "$delivery/cashcast-local-candidate-v18.zip" data/raw/handoff-packages/cashcast-local-candidate-v18
Expand-Archive "$delivery/cashcast-risk-addon-v21.zip" data/raw/handoff-packages/cashcast-risk-addon-v21
foreach ($n in 25,29,31) { Expand-Archive "$delivery/cashcast-risk-addon-v$n.zip" data/raw/handoff-packages }
$base=(Resolve-Path data/raw/handoff-packages/cashcast-local-candidate-v18).Path
$addon31=(Resolve-Path data/raw/handoff-packages/cashcast-risk-addon-v31).Path
& $tab "$addon31/predict.py" --snapshot C:/input/snapshot.json --manifest "$addon31/manifest.json" --base-manifest "$base/manifest.json" --tabular-python $tab --chronos-python $chr --output C:/output/forecast31.json
```

Формат snapshot.json — ForecastInputCodec. Аналогично запускаются25/29 заменой
пути дополнения. Все вызывают неизменённый baseline18. Поддерживается30дней;
неподдержанный вход явно unavailable, исходный fallback сохраняется. Целые копейки
и денежное согласование относятся к отдельному reconciled_scenario, нативные потоки
не подменяются. Score некалиброванный. Последние веса — август2026, автоматического
дообучения нет; runtime сообщает устаревание по своему контракту.

Полный research restore нужен для повторной оценки и обучения. Команды обучения
запускаются только в новой копии с пустыми выходными каталогами, по одному разу.
Не перезапускайте завершённые опыты и тихие живые процессы.

```powershell
$dataset='C:/DTSU/vsprojects/cashcast/cashflow_dataset_participants.zip'
# Сначала команды24–28 из B-REPRODUCE.md;24 — только evaluate, не train.
& $tab -u -m evaluation.liquidity_risk.diverse_risk
& $tab -u -m evaluation.liquidity_risk.block_flows --zip $dataset
& $tab -u -m evaluation.liquidity_risk.long_history_risk --zip $dataset
& $tab -u -m evaluation.liquidity_risk.diverse_robustness
& $tab -u -m evaluation.liquidity_risk.long_robustness
& $tab -u -m evaluation.liquidity_risk.rolling_reserve_quantiles --zip $dataset
& $tab -u -m evaluation.liquidity_risk.block_mean_median --zip $dataset
& $tab -u -m evaluation.liquidity_risk.rolling_block_flows --zip $dataset
& $tab -u -m evaluation.liquidity_risk.standalone_long_risk
New-Item -ItemType Directory -Force data/raw/b-logs | Out-Null
& $tab research_handoff/run_tests.py *> data/raw/b-logs/continued-tests.log
if ($LASTEXITCODE -ne 0) { throw 'Профильные тесты не прошли' }
& $tab -m evaluation.liquidity_risk.package_diverse
& $tab -m evaluation.liquidity_risk.package_long
$addon29=(Resolve-Path data/raw/b-packages/cashcast-risk-addon-v29).Path
$addon31=(Resolve-Path data/raw/b-packages/cashcast-risk-addon-v31).Path
& $tab -u -m evaluation.liquidity_risk.verify_diverse_runtime --zip $dataset --addon $addon29 --base $base --tabular-python $tab --chronos-python $chr --output data/raw/check29
& $tab -u -m evaluation.liquidity_risk.verify_long_runtime --zip $dataset --addon $addon31 --base $base --tabular-python $tab --chronos-python $chr --output data/raw/check31
& $tab research_handoff/collect_continued.py --tests-log data/raw/b-logs/continued-tests.log
& $tab research_handoff/package_b.py bundle --commit <reviewed-code-commit> --output C:/new/output/continued-bundle --addons 25 29 31
```

Протоколы29–37 в journal фиксируют параметры, бюджет, ранние ограничения и критерии
переноса. Late не является слепым контролем. results-continued/status.json явно
перечисляет завершённые и ожидающие опыты; collector не копирует незавершённые итоги.
JSON.gz читаются через gzip.open(path,'rt',encoding='utf-8'). Сборка архива проверяет
SHA весов и CRC внутренних ZIP; новый каталог не перезаписывает старую передачу.
