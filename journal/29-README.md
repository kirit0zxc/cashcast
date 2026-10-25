# Исследовательское дополнение29

ПредварительноTP10/FP58/FN1/TN789на858зависимыхретроспективныхокнах,11positives.
Текущая9/155/2/692;18:9/52/2/795;21:10/71/1/776;25:10/67/1/780.
Независимогоконтролянет. Это не production и не подтверждённаякалиброваннаявероятность.

Нужен исходныйпакет18 сmanifestSHAизэтогодополнения. Python3.12, прежниеокружения
research_handoff/requirements-tabular.txt иrequirements-chronos.txt;новыхзависимостейнет.
Manifestзакрепляет80весов:40LightGBM25+40CatBoost29,восемьмесячныхсрезов,пятьгрупп.

```powershell
$env:HF_HUB_OFFLINE='1'
$env:PYTHONDONTWRITEBYTECODE='1'
& <tabular-python> predict.py --snapshot <input.json> --manifest manifest.json --base-manifest <package18/manifest.json> --tabular-python <tabular-python> --chronos-python <chronos-python> --output <output.json>
```

Путиабсолютные. ФорматForecastInputCodec,30дней,безявныхпланов/recurrences/сценария.
ПримерJSONестьв18. Приотсутствиипричинногосреза/недоступномbaseline—явныйunavailable.
Контрольнаякомпанияsha256byte0%5=0 получаетmean5;остальные—модельисключённойгруппы
sha256byte1%5. Весаобучалисьтолькоприas_of+37<=training_cutoff и безheldout.
Последнийсрезавгуст2026;автоматическогопереобучениянет,staleness_daysвыводится.

Score=.5*CatBoost+.5*LightGBM25; предупреждение=risk18 OR score>=.05.
ПолитикавыбранатольконаdevelopmentJan–Jun. probability_any_negative=null,
cat_score/lightgbm25_score/uncalibrated_score — некалиброванныеоценкикомпонентов.
Точка,current,потоки,benchmark75/25исогласованныйсценарийкопируютсяиз18безизменений.

Протокол,фактическаяконфигурация,аудиты,SHAиметрикивreports. Первичныйкод29
сохранилselection-файлпередпозднимэтапом,ноSHAselectionвычислилприcompleted;
этоограничениеprovenance,а не заявлениераннегоSHA. Повторноеобучениерадиэтогонепроводилось.
Проверкиустойчивости32 — отдельнаядиагностика, никакойseed изнеёневыбирается.
