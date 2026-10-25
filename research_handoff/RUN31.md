# Запуск выбранной модели №31

Рабочая ветка: `agents/b-model-research-20261025`. Запускайте команды из корня
рабочей копии этой ветки. Итоговый выбор и ограничения — [FINAL31-REPORT.md](FINAL31-REPORT.md).
Повторное обучение для запуска не требуется. Нужны Windows, Python 3.12 и два
архива с уже проверенными весами:

| Архив | Размер, байт | SHA256 |
|---|---:|---|
| cashcast-local-candidate-v18.zip | 959877143 | `5d39f25ea0915b1ecae9a47221806ff8892af88f94b421eac7c8da186d854a61` |
| cashcast-risk-addon-v31.zip | 6901152 | `5ebf18476b096226b2690279ddebef18692e727530f4772680b810dfd6c9ca73` |

Оба файла находятся внутри проверенного промежуточного архива на машине исследования:
`C:/DTSU/vsprojects/cashcast/model-research-b/data/raw/b-delivery/continued/cashcast-b-checkpoint-20261025.zip`.
SHA256 внешнего архива:
`ed78a230491bfd3201d8bb27a0b753bec73dced9348c2ea31426928cc14ce1a3`.
Распакуйте его в новый каталог; внутри появится папка `cashcast-b-checkpoint-20261025`.
В ней находятся оба ZIP и `predictions31.json` для проверки воспроизводимости.
Отдельный проверенный ZIP31 также есть в `data/raw/b-delivery/continued-runtime-check/`,
а ZIP18 — в `data/raw/handoff-downloads/`.
Для другого компьютера передайте эти два архива отдельно. Веса не включены в Git;
старый release `model-research-handoff-20261025` содержит №18, но ещё не содержит №31.
Клонирование одной ветки не заменяет передачу архивов.

Если окружения ещё не созданы, один раз выполните:

```powershell
py -3.12 -m venv .venv/research
py -3.12 -m venv .venv/chronos
& .venv/research/Scripts/python.exe -m pip install -r research_handoff/requirements-tabular.txt
& .venv/chronos/Scripts/python.exe -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.1
& .venv/chronos/Scripts/python.exe -m pip install -r research_handoff/requirements-chronos.txt
```

Использованы Python 3.12.15, LightGBM 4.6.0, CatBoost 1.2.8,
chronos-forecasting 2.3.2, transformers 5.20.2. Остальные версии закреплены в
requirements и `B-ENVIRONMENT-*.json`. Установка требует сети, сам inference локальный.

Проверьте SHA и распакуйте в новый пустой каталог. №18 не имеет верхней папки в ZIP;
№31 уже содержит `cashcast-risk-addon-v31/`, поэтому назначения распаковки различаются.

```powershell
$delivery='C:/path/to/extracted/cashcast-b-checkpoint-20261025'
$expected=@{
  'cashcast-local-candidate-v18.zip'='5d39f25ea0915b1ecae9a47221806ff8892af88f94b421eac7c8da186d854a61'
  'cashcast-risk-addon-v31.zip'='5ebf18476b096226b2690279ddebef18692e727530f4772680b810dfd6c9ca73'
}
foreach ($name in $expected.Keys) {
  if ((Get-FileHash -LiteralPath "$delivery/$name" -Algorithm SHA256).Hash -ne $expected[$name]) {
    throw "Неверный SHA256: $name"
  }
}
$packages=Join-Path (Get-Location) 'data/raw/run31-packages'
if (Test-Path -LiteralPath $packages) { throw 'Выберите новый пустой каталог распаковки' }
New-Item -ItemType Directory -Path $packages | Out-Null
Expand-Archive -LiteralPath "$delivery/cashcast-local-candidate-v18.zip" -DestinationPath "$packages/cashcast-local-candidate-v18"
Expand-Archive -LiteralPath "$delivery/cashcast-risk-addon-v31.zip" -DestinationPath $packages
```

Запуск. Замените `$snapshot` абсолютным путём к своему JSON-снимку
`ForecastInputCodec`, версия1. Сырые банковские CSV этот CLI не импортирует.
Пример структуры есть в `$base/example-input.json`, он содержит синтетические данные.
Для реального прогноза сохраняйте всю доступную собственную историю, включая её
начальную дату: урезание истории меняет признаки. Горизонт — 30 дней; планы,
recurrences и scenario данным исследовательским runtime не поддерживаются.

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:HF_HUB_OFFLINE='1'
New-Item -ItemType Directory -Force data/raw/tmp | Out-Null
$env:TEMP=(Resolve-Path data/raw/tmp).Path
$env:TMP=$env:TEMP
$tab=(Resolve-Path .venv/research/Scripts/python.exe).Path
$chr=(Resolve-Path .venv/chronos/Scripts/python.exe).Path
$base=(Resolve-Path "$packages/cashcast-local-candidate-v18").Path
$addon=(Resolve-Path "$packages/cashcast-risk-addon-v31").Path
$snapshot='C:/input/snapshot.json'
$output=Join-Path (Get-Location) 'data/raw/forecast31.json'
& $tab "$addon/predict.py" --snapshot $snapshot --manifest "$addon/manifest.json" --base-manifest "$base/manifest.json" --tabular-python $tab --chronos-python $chr --output $output
if ($LASTEXITCODE -ne 0) { throw 'Ошибка запуска №31; проверьте вход и manifest' }
```

При доступном прогнозе ожидаются `candidate="cashcast-research-31"`,
`risk.new_gap_warning` и `risk_extension.uncalibrated_score`. Правило предупреждения:
базовый сигнал №18 OR score≥0.1. `probability_any_negative=null`: score не вероятность.
Поля `training_cutoff`/`staleness_days` показывают возраст выбранных весов.
При отсутствии причинного checkpoint или доступного базового риска возвращается
явный `risk_extension.status="unavailable"`; проверяйте статус перед использованием.
Не подменяйте отсутствующий результат отрицательным предупреждением.

Для проверки на исходном приватном датасете организаторов (передаётся отдельно)
также нужен эталон `predictions31.json` из указанного промежуточного архива.
Это сохранённые риск-прогнозы, без исходных операций. В новой копии сначала
восстановите его в ожидаемый путь; исходный полный research restore A этого файла
ещё не содержит. На машине исследования файл уже находится на месте.

```powershell
$dataset='C:/DTSU/vsprojects/cashcast/cashflow_dataset_participants.zip'
if ((Get-FileHash -LiteralPath $dataset -Algorithm SHA256).Hash -ne 'e753802b7f7a2eecb7b5a558f9923b529e711c40fe431774750904b62ec79987') {
  throw 'Неверный датасет'
}
$reference='data/raw/long-history-risk-v31/predictions.json'
if (-not (Test-Path -LiteralPath $reference)) {
  New-Item -ItemType Directory -Force data/raw/long-history-risk-v31 | Out-Null
  Copy-Item -LiteralPath "$delivery/predictions31.json" -Destination $reference
}
if ((Get-FileHash -LiteralPath $reference -Algorithm SHA256).Hash -ne '8529ef437c190dae264b5eb9a2da20fd1dbfab9246ad5910732f1836c3879349') {
  throw 'Неверный эталон predictions31.json'
}
& $tab -u -m evaluation.liquidity_risk.verify_long_runtime --zip $dataset --addon $addon --base $base --tabular-python $tab --chronos-python $chr --output data/raw/check31-new
if ($LASTEXITCODE -ne 0) { throw 'Проверка №31 не прошла' }
```

Это воспроизводит 858 scores и пять полных CLI, проверяет future/foreign и unsupported.
Каталог `check31-new` должен быть новым. Уже завершённая проверка после чистой
распаковки сохранена в [verification.json](results-continued/runtime31-unpacked/verification.json).
База данных и production для запуска не нужны. Деньги — целые копейки; отдельный
`reconciled_scenario` обеспечивает согласованность, нативные потоки не заменяются.
