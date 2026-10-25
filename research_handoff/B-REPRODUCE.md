# Воспроизведение исследования B

База передачи: ae45cf36cea8eb9c7909436e5ac62c0f6edfb85a.
Финальный commit/tree кода указан в bundle-manifest.json; это source.zip внутри
cashcast-b-handoff-20261025.zip. Внешний SHA архива — в соседнем receipt.json.
Результаты B-MORNING-REPORT.md; прежняя инструкция A — START_HERE.md (история,
его фраза «24 ещё не оценён» относится к моменту передачи, а не текущему состоянию).

## Состав

- cashcast-local-candidate-v18.zip и cashcast-risk-addon-v21.zip: исходные байты A,
  SHA из assets.json; прежние лидеры сохранены.
- cashcast-risk-addon-v25.zip: 40 причинных моделей, runtime, manifest, протокол,
  отчёты. Кандидат предварительный, не включён в production.
- source.zip: точный Git commit; research_handoff/results содержит агрегированные
  показатели, MAE/RMSE7/14/30, компании/периоды, калибровочную диагностику и проверки.
- predictions25.json: сохранённые риск-прогнозы, без банковских операций и признаков.
- bundle-manifest.json: SHA и размер каждого файла. Окружения и датасет не входят.

Для чтения *.json.gz используйте Python gzip.open(path,'rt',encoding='utf-8').
local-artifact-index.json содержит SHA оставшихся локальных прогнозов и весов24–28;
их пути отсчитываются от корня рабочей копии. Они сохранены в data/raw, в Git не входят.

## Окружения

Python3.12.15, Windows/CPU. Использованы ровно requirements-tabular.txt и
requirements-chronos.txt; фактические версии — B-ENVIRONMENT-*.json. В новой копии:

```powershell
py -3.12 -m venv .venv/research
py -3.12 -m venv .venv/chronos
& .venv/research/Scripts/python.exe -m pip install -r research_handoff/requirements-tabular.txt
& .venv/chronos/Scripts/python.exe -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.1
& .venv/chronos/Scripts/python.exe -m pip install -r research_handoff/requirements-chronos.txt
New-Item -ItemType Directory -Force data/raw/tmp | Out-Null
$env:TEMP=(Resolve-Path data/raw/tmp).Path
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:HF_HUB_OFFLINE='1'
$tab=(Resolve-Path .venv/research/Scripts/python.exe).Path
$chr=(Resolve-Path .venv/chronos/Scripts/python.exe).Path
```

Флаг PYTHONDONTWRITEBYTECODE обязателен для исходного21 с первого импорта:
его manifest хеширует два pyc, которые Python иначе переписывает. При уже нарушенном
manifest восстановите точные файлы из исходного SHA-проверенного ZIP; не пересчитывайте
manifest под повреждённый пакет. №25 не упаковывает pyc. Не требуется сеть для inference.

Выберите один маршрут восстановления. Для **runtime-only** используйте новый
пустой каталог: оригинальные18/21 не имеют общего верхнего каталога, поэтому
обязательно распаковываются каждый в свой подкаталог. ZIP25 уже содержит префикс.

```powershell
$delivery='C:/path/to/extracted/cashcast-b-handoff-20261025'
Expand-Archive "$delivery/cashcast-local-candidate-v18.zip" data/raw/handoff-packages/cashcast-local-candidate-v18
Expand-Archive "$delivery/cashcast-risk-addon-v21.zip" data/raw/handoff-packages/cashcast-risk-addon-v21
Expand-Archive "$delivery/cashcast-risk-addon-v25.zip" data/raw/handoff-packages
```

Для **полного research restore** вместо этих команд используйте чистую копию
без data/raw/handoff-packages: restore.py сам создаёт18/21 и не перезаписывает
существующие каталоги. Нужны все5архивов приватного release
model-research-handoff-20261025; restore.py проверяет их по assets.json.
После restore распакуйте только дополнение25:

```powershell
& $tab research_handoff/restore.py --downloads C:/path/to/all-five-release-assets
Expand-Archive C:/path/to/cashcast-risk-addon-v25.zip data/raw/handoff-packages
```

После любого из двух маршрутов:

```powershell
$base=(Resolve-Path data/raw/handoff-packages/cashcast-local-candidate-v18).Path
$addon21=(Resolve-Path data/raw/handoff-packages/cashcast-risk-addon-v21).Path
$addon25=(Resolve-Path data/raw/handoff-packages/cashcast-risk-addon-v25).Path
& $tab research_handoff/run_tests.py
& $chr -m unittest evaluation.liquidity_risk.test_cumulative_flows evaluation.liquidity_risk.test_flow_finetune evaluation.liquidity_risk.test_finetune
```

## Реальный inference

snapshot.json соответствует ForecastInputCodec; синтетический пример есть в18.
Передавайте абсолютные пути. Дополнение25 вызывает неизменённый baseline18.

```powershell
Push-Location $base
& $tab -m evaluation.liquidity_risk.offline_bundle --snapshot C:/input/snapshot.json --manifest "$base/manifest.json" --tabular-python $tab --chronos-python $chr --output C:/output/forecast18.json
Pop-Location
& $tab "$addon21/predict.py" --snapshot C:/input/snapshot.json --manifest "$addon21/manifest.json" --base-manifest "$base/manifest.json" --tabular-python $tab --chronos-python $chr --output C:/output/forecast21.json
& $tab "$addon25/predict.py" --snapshot C:/input/snapshot.json --manifest "$addon25/manifest.json" --base-manifest "$base/manifest.json" --tabular-python $tab --chronos-python $chr --output C:/output/forecast25.json
```

Исследовательский режим30дней. Для неподдерживаемого запроса возвращается явный
unavailable; нативный fallback не подменяется. Полный контракт — README пакетов.
Точка и нативные потоки различаются; денежная согласованность гарантируется отдельно
для reconciled_scenario. Новое значение probability_any_negative не изобретается.
Последняя дата весов25 — август2026; автоматического обновления нет, staleness указан.

## Оценка и обучение

Организаторский ZIP предоставляется отдельно: SHA256
e753802b7f7a2eecb7b5a558f9923b529e711c40fe431774750904b62ec79987.
В данной рабочей копии: C:/DTSU/vsprojects/cashcast/cashflow_dataset_participants.zip.
Переменная $dataset ниже должна указывать на этот же проверенный набор.
Для полного пересчёта нужен research restore, а не только runtime ZIP18/21/25.
Обучающие команды запускаются один раз в новой копии с ещё не созданными выходами;
не запускайте повторное обучение в завершённом каталоге или из-за тихого лога.

```powershell
$dataset='C:/DTSU/vsprojects/cashcast/cashflow_dataset_participants.zip'
# 24 — только оценка уже обученных checkpoint100/300, никогда train.
& $chr -u -m evaluation.liquidity_risk.cumulative_flows evaluate
& $tab -m evaluation.liquidity_risk.research_audit
# 25 — фиксированное company crossfit, ранний выбор до поздней оценки.
& $tab -u -m evaluation.liquidity_risk.company_crossfit
# 26 — одна residual-модель; 27 — без обучения; 28 — три диагностических повтора.
& $tab -u -m evaluation.liquidity_risk.chronos_residual --zip $dataset
& $tab -u -m evaluation.liquidity_risk.weighted_reconciliation
& $tab -u -m evaluation.liquidity_risk.crossfit_robustness
# Полные проверки сохранённых пакетов (в этой копии уже завершены).
& $tab -u -m evaluation.liquidity_risk.verify_offline --zip $dataset --bundle $base --tabular-python $tab --chronos-python $chr --reserve-source data/raw/forecast-reserve-v18 --reserve-model forecast6 --output data/raw/check18
& $tab -u -m evaluation.liquidity_risk.verify_offline --zip $dataset --bundle $base --tabular-python $tab --chronos-python $chr --reserve-source data/raw/forecast-reserve-v18 --reserve-model forecast6 --output data/raw/check18 --edge-only
& $tab -u -m evaluation.liquidity_risk.verify_rolling_runtime --zip $dataset --addon $addon21 --base $base --tabular-python $tab --chronos-python $chr --output data/raw/check21
& $tab -u -m evaluation.liquidity_risk.verify_crossfit_runtime --zip $dataset --addon $addon25 --base $base --tabular-python $tab --chronos-python $chr --output data/raw/check25
```

Протоколы и все отказы — journal/24-RESULTS-B.md,25_company_crossfit.md,
25-RESULTS-B.md,26_chronos_residual.md,26-RESULTS-B.md,27_weighted_reconciliation.md,
27-RESULTS-B.md,28_crossfit_robustness.md,28-RESULTS-B.md и DO_NOT_REPEAT.md.
Повторно просмотренные поздние окна не становятся слепым контролем.

Сборка неизменного дополнения/пакета после проверок:

```powershell
& $tab -m evaluation.liquidity_risk.package_crossfit
& $tab research_handoff/package_b.py evidence
& $tab research_handoff/package_b.py bundle --commit <reviewed-code-commit> --output C:/new/output/cashcast-b-handoff-20261025
```

Архивы создаются только в новом каталоге; существующие результаты не затираются.
Банковские операции и признаки отсутствуют в явном списке упаковки. Исторический
source.zip содержит прежние исходники репозитория; это не снимок всего рабочего диска.
