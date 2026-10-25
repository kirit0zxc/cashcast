# Исследовательское дополнение31

Предварительныйрезультат858зависимыхокон:TP10/FP53/FN1/TN794;precision.158730,
recall.909091,F1.270270. Исходный18:TP9/FP52/FN2;25:TP10/FP67/FN1;
29:TP10/FP58/FN1. Периодыадаптивные,новогонезависимогоконтролянет.

40LightGBM,86признаков:34из25+52статистикипрошлыхпотоковза28/84/180/365дней.
Длиннаяисторияберёттолькособственныеоперации<=as_of. Минимальныйдатумсвоейистории
долженсохранятьсявForecastInput; урезаниеисториивходаизменяетпрогноз.
Срезтолькосдатой<=as_of,последнийавгуст2026,staleness_daysявен. Автообновлениянет.
Группыкомпаний/пурж37/равныевесакак25;контрольныекомпаниивсегдаисключеныизобучения.

Нужен неизменённыйпакет18 и прежниеresearch/chronosокруженияPython3.12.
Путиабсолютные;сырьё/обучающиепризнаки/pycневключены. Примерснимкав18.

```powershell
$env:HF_HUB_OFFLINE='1'
$env:PYTHONDONTWRITEBYTECODE='1'
& <tabular-python> predict.py --snapshot <input.json> --manifest manifest.json --base-manifest <package18/manifest.json> --tabular-python <tabular-python> --chronos-python <chronos-python> --output <output.json>
```

Политикаrisk18 OR extended_score>=.1выбранатольконаdevelopmentJan–Jun.
Сыройscoreнекалиброван;probability_any_negative=null. Точка/потоки/current/
benchmark75/25исогласованныйсценарийкопируютсяиз18. Длянеподдержанного30-дневного
входабезпланов/recurrences/сценария—явноеunavailable,согласноправилам18.
Отсутствиепричинныхвесовтакжеunavailable. Productionнеизменён.

Протокол,аудиты,веса,SHAвmanifest/reports. Проверки33оцениваютустойчивость,
невыбираютновуюмодель. Результатнеравенгарантиикачествадляновыхданных.
