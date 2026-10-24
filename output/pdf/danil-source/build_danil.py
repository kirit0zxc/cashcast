from __future__ import annotations

import hashlib
import html
import io
import json
import re
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

ROOT=Path(__file__).resolve().parents[3]
TMP=ROOT/'tmp/pdfs'
TMP.mkdir(parents=True,exist_ok=True)
OUT=ROOT/'output/pdf'
FINAL=OUT/'CashCast-Danil-forecasting-extract.pdf'
ATLAS=OUT/'CashCast-project-and-pitch-complete-schematics.pdf'
SHA='cbe3f87dd1d7d914942f85291f5986e7af21effb'
BASE='e8f93fc5c9db4dc8f7d3535a0d8b9dde47505615'
INK=colors.HexColor('#173744');TEAL=colors.HexColor('#147D89')
GRAY=colors.HexColor('#60747C');PALE=colors.HexColor('#EEF6F7');RULE=colors.HexColor('#D5E3E7')
for n,f in [('Body','calibri.ttf'),('Bold','calibrib.ttf'),('Mono','consola.ttf')]:
    pdfmetrics.registerFont(TTFont(n,str(Path(r'C:\Windows\Fonts')/f)))
pdfmetrics.registerFontFamily('Body',normal='Body',bold='Bold',italic='Body',boldItalic='Bold')

def norm(s):return s.translate(str.maketrans({'—':'-','–':'-','‑':'-','\u00a0':' ','\u202f':' '}))
def inline(s):
    s=html.escape(norm(s))
    s=re.sub(r'\*\*([^*]+)\*\*',r'<b>\1</b>',s)
    s=re.sub(r'`([^`]+)`',r'<font name="Mono" size="9">\1</font>',s)
    return s.replace('\n','<br/>')

buf=io.BytesIO();c=canvas.Canvas(buf,pagesize=A4,pageCompression=1)
W,H=A4;X=43;CW=W-X*2;y=0;page=0

def para(s,size=10.6,color=INK,bold=False,gap=7,x=None,width=None):
    global y
    p=Paragraph(inline(s),ParagraphStyle('p',fontName='Bold' if bold else 'Body',fontSize=size,
             leading=size*1.32,textColor=color,splitLongWords=1))
    xx=X if x is None else x;ww=CW if width is None else width
    _,hh=p.wrap(ww,10000)
    assert y-hh>50,(page,s[:70],y,hh)
    p.drawOn(c,xx,y-hh);y-=hh+gap

def head(title):
    global y,page
    if page:c.showPage()
    page+=1;y=H-53
    c.setFillColor(TEAL);c.setFont('Bold',8.5);c.drawString(X,H-25,'CASHCAST / ДАНИЛ / ПРОГНОЗ, РИСК И СЦЕНАРИИ')
    c.setFont('Body',8);c.setFillColor(GRAY);c.drawRightString(W-X,H-25,'24.10.2026')
    c.setStrokeColor(RULE);c.line(X,H-33,W-X,H-33);c.line(X,34,W-X,34)
    c.setFont('Body',8);c.drawString(X,21,'Техническая выжимка по роли; исторические и текущие результаты разделены')
    c.drawRightString(W-X,21,f'{page} / 10')
    para(title,22,bold=True,gap=13)

def sub(s):
    global y
    y-=3;para(s,12.4,TEAL,True,gap=6)

def bullet(s):para('• '+s,gap=6)

def table(headers,rows,ratios,size=9.1):
    global y
    widths=[CW*z for z in ratios]
    for i,row in enumerate([headers]+rows):
        ps=[];heights=[]
        for s,w in zip(row,widths):
            p=Paragraph(inline(str(s)),ParagraphStyle('cell',fontName='Bold' if i==0 else 'Body',
                  fontSize=size,leading=size*1.27,textColor=colors.white if i==0 else INK,splitLongWords=1))
            _,hh=p.wrap(w-12,10000);ps.append(p);heights.append(hh)
        rh=max(heights)+12
        assert y-rh>50,(page,row,y,rh)
        c.setFillColor(INK if i==0 else PALE if i%2 else colors.white);c.rect(X,y-rh,CW,rh,fill=1,stroke=0)
        xx=X
        for p,w,hh in zip(ps,widths,heights):p.drawOn(c,xx+6,y-6-hh);xx+=w
        c.setStrokeColor(RULE);c.setLineWidth(.35);c.line(X,y-rh,X+CW,y-rh);y-=rh
    y-=9

def source(label,path,base=SHA):
    global y
    url=f'https://github.com/kirit0zxc/cashcast/blob/{base}/{path}'
    p=Paragraph('<link href="'+url+'" color="#147D89">'+html.escape(label)+'</link>',
                ParagraphStyle('src',fontName='Body',fontSize=8.3,leading=11,textColor=GRAY))
    _,hh=p.wrap(CW,10000);assert y-hh>45;p.drawOn(c,X,y-hh);y-=hh+4

head('1. Твой технический участок')
para('**Данил: прогноз остатка, кассовый разрыв, сценарии, объяснения и качество.** Это выборка из общей техдокументации по зоне, указанной в персональной памятке; она не устанавливает личное авторство коммитов.',gap=11)
sub('Как назвать модель')
para('Гибридная статистическая модель денежного потока: календарь обязательств + регулярные платежи + сезонная оценка нерегулярного потока + парный недельный block bootstrap. Активный default - `seasonal-guarded-2.0-w84`.')
sub('Алгоритм, который нужно уметь объяснить')
for s in [
 '1. Зафиксировать один RUB-счёт и as_of. Начальный остаток - последний EOD плюс известные движения после его даты; отсутствие подтверждения явно отмечается.',
 '2. Отделить известные планы и регулярности. Однозначно подходящий план заменяет occurrence регулярности, чтобы один платёж не учитывался дважды.',
 '3. В пригодном окне до 84 дней исключить регулярные операции из остаточного потока. Рассчитать ожидаемые поступления и списания по дням недели.',
 '4. Построить 200 траекторий: совместно выбирать исторические недельные блоки притока/оттока с согласованным weekday и фиксированным seed.',
 '5. К остаточным траекториям добавить календарные известные потоки. Для каждого дня получить p10/p50/p90 и компоненты объяснения.',
 '6. Найти отрицательные эпизоды p50, оценить максимальную нехватку и сравнить альтернативные условия с сохранённой базой.',
]:para(s,gap=7)
sub('Формула одной траектории')
para('`B_t(k) = B_0 + sum_{d<=t}(known_in_d - known_out_d + residual_in_d(k) - residual_out_d(k))`',size=10)
para('p50 - медиана траекторий, а не обязательно сумма средних потоков. p10/p90 - эмпирические границы; они не гарантируют будущий коридор.',size=10,color=GRAY)
source('Метод и контракты: forecasting.md','specs/forecasting.md')

head('2. Вход, причинность и частичный расчёт')
table(['Вход ForecastInput','Смысл и ограничение'],[
 ['account_id; as_of','Один счёт RUB; операции/EOD не позже среза. Планы должны быть доступны на as_of'],
 ['horizon_days; seed','API: 1-180 дней, default 30; default seed 42. Seed фиксирует случайную выборку'],
 ['opening_balance_minor','Целые копейки; подтверждённый либо расчётный начальный остаток с warning'],
 ['txns; daily_balances','Факты и EOD отдельно. Отсутствующий день не доказывает нулевой поток'],
 ['planned_events; recurrences','Известные обязательства, remaining после аллокаций; регулярности - оценка'],
 ['scenario; data_version','Сценарные изменения и версия полного входа; модель закрепляется у run'],
],[.37,.63])
sub('Защита от неподходящей истории')
para('Quality сверяет изменение EOD с потоком операций и ограничивает статистическую историю после последней несверки. При восстановлении opening учитываются известные последующие факты; суммы не «исправляются» ради хорошего результата.')
table(['Режим','Как трактовать'],[
 ['plan_only','Нет пригодной наблюдаемой истории: вывод строится с явными входными допущениями'],
 ['point_only','Точечный fallback. p10/p90 могут совпасть с p50; коридор нельзя выдавать за гарантию'],
 ['empirical','Data gate симуляции: ≥28 пригодных дней, свежий EOD не старше 3 дней, согласованный opening'],
],[.22,.78])
para('Gate потенциальной вероятности требует ≥56 дней, но даже его прохождение НЕ включает процент в продукте. Frozen bootstrap имеет собственную проверку надёжности; один флаг quality не гарантирует непустую выборку.',size=9.8,color=GRAY)
sub('Incremental: оптимизация исполнения')
para('Совместимый checkpoint `ledger-update-v2` позволяет пересчитать изменённые операции, группы регулярности и дневные дельты, переиспользуя bootstrap-сетку. При изменении допустимых блоков сетка создаётся заново. Календарное сопоставление и итоговые квантили пересчитываются.')
para('Первый запуск, несовместимый/повреждённый checkpoint, другие model/seed/horizon и сценарии требуют full. Идентичный повтор - dedupe, а не incremental. API всё ещё готовит полный snapshot.',size=10)
para('Это не полный журнал версий БД: поздняя загрузка операции с прошлой датой может изменить новый расчёт старого среза. Уже сохранённый run остаётся неизменным.',size=9.5,color=GRAY)
source('Контракт partial execution','specs/incremental-forecast.md')

head('3. Кассовый разрыв и его объяснение')
para('Разрыв - непрерывный интервал **отрицательных остатков на конец дня**. Карточка анализирует начальный остаток на as_of и сохранённые дневные p50. Она не обучает отдельный классификатор.')
table(['Поле / состояние','Что объяснять'],[
 ['existing','Минус уже на as_of. Настоящее начало эпизода неизвестно'],
 ['new','Новый минус после среза; возможен и после восстановления существовавшего дефицита'],
 ['recovery_date','Первая дата остатка ≥0. День восстановления не входит в отрицательную длительность'],
 ['max_deficit_minor','Максимальная глубина минуса; карточка включает также opening на as_of'],
 ['duration_is_lower_bound','Начало неизвестно и/или восстановления в горизонте нет'],
 ['gap / no_gap / insufficient_data','no_gap допустим лишь при пригодной истории. Недостаток данных не равен безопасности'],
],[.37,.63])
sub('Что означают «причины»')
para('`causes` - знаковое разложение исходного минимума: начальный остаток, известные планы, оценочные потоки и техническая поправка к медиане. Сумма равна `causes_balance_minor`. Это состав расчёта, а не доказательство причинности. План не является фактической оплатой.')
sub('Вероятность удержана сознательно')
para('Текущая guarded-обёртка возвращает `probability_negative=null`, `probability_any_negative=null`, `risk.available=false`. Дата и сумма p50 при этом доступны. Внутренняя доля отрицательных траекторий является модельным score; её нельзя автоматически считать проверенной вероятностью.')
sub('Дополнение нового main cbe3f87')
para('Карточка дополнена `days_until_new_gap` и `required_reserve_minor`. Последнее - минимальная постоянная добавка к opening, делающая ряд неотрицательным; это максимум дефицита в иной интерпретации. Резерв нужен с начала ряда, не является кредитом и не учитывает возврат. Для займа используется financing preview.',size=10)
para('Граница: один счёт, дневной EOD, не деньги всей компании и не внутридневная ликвидность. Будущее финансирование не отменяет минус, существовавший на as_of.',size=10,color=GRAY)
source('Полная семантика карточки','specs/cash-gaps.md')

head('4. Сценарии, сравнение и финансовый пульс')
table(['Сценарий','Параметры и точная семантика'],[
 ['delay_event','target_id известного активного события; shift_days ≥0. Закрытое событие переносить нельзя'],
 ['reduce_irregular_inflow','factor 0-1: множитель только нерегулярного притока, а не всей выручки'],
 ['add_expense','Положительные amount_minor и on_date строго после as_of внутри горизонта'],
 ['increase_recurring','Множитель ≥1 для известной регулярности; API имеет собственные границы factor. UI использует выбранную цель'],
],[.35,.65])
sub('Почему нужен тот же seed')
para('Сценарий работает на копии frozen-входа базы. Сохраняются исходные факты, as_of, horizon, data_version, model_version и согласованная случайная выборка. Один seed уменьшает влияние случайного различия симуляций на сравнение. Создаётся отдельный job/run; старый результат не меняется.')
para('GET comparison проверяет company/account, as_of, horizon, data/model version, seed и совпадение дат. Выход: дневная разность `scenario_p50 - base_p50`. Самостоятельный сценарий с другим seed возможен, но paired comparison с базой отклоняется.',size=10)
sub('Не смешивать три разных механизма')
table(['Механизм','Результат и побочные эффекты'],[
 ['Обычный scenarios POST','1-50 изменений, полный расчёт закреплённой моделью, новый сохранённый прогноз'],
 ['cash-gap-preview POST','1-3 гипотезы delay/financing; сдвиг сохранённой медианы. Нет нового job, записи плана и пересчёта вероятности'],
 ['Финансовый пульс GET','Frozen p50 и snapshot: подушка, гипотезы действий, расходы и клиентский stress. Не live-пересчёт прогноза'],
],[.34,.66])
para('В preview перенос расхода разрешён для допустимой закупки с согласованной гипотезой отсрочки. Зарплата, налог, аренда, кредит и неизвестный расход защищены. Финансирование учитывает тело, стоимость, дату возврата и долг за горизонтом. Эффект может быть отрицательным.',size=10)
para('В пульсе техническая поправка к p50 не становится выручкой. Оценки экономии могут пересекаться; их нельзя суммировать как гарантированный эффект.',size=10,color=GRAY)
source('Сценарии и интерпретация','specs/forecasting.md')
source('Frozen-основа финансового пульса','specs/pulse.md')

head('5. Качество: что именно измерено')
para('Исходный B4: синтетический датасет организаторов - 150 компаний, 222 420 операций, 01.10.2024-30.09.2026. Горизонт 30 дней, seed 42, 200 bootstrap-путей. Все числа ниже - из опубликованных отчётов, без нового прогона.')
para('Baseline берёт средний дневной приток и отток за последние 7 дней и повторяет их на горизонт, добавляя активные планы. Неопределённость не оценивается: p10=p50=p90.',size=10)
table(['Эксперимент','Baseline / прежняя','Seasonal / guarded'],[
 ['B4: MAE остатка, сентябрь','2 775 628,60 ₽','1 072 364,48 ₽'],
 ['B4: RMSE остатка, сентябрь','6 548 194,91 ₽','2 686 386,56 ₽'],
 ['B6: MAE, те же 256 случаев','1 427 246,86 ₽','1 425 436,50 ₽'],
],[.43,.285,.285],size=9.5)
para('B4: 122 company-cutoff окна / 3 660 дней; 84 дня выбраны на 517 validation-окнах среди 28/56/84. B6: другой набор - 256 окон / 7 680 дней; нельзя сравнивать его MAE напрямую с B4 как изменение точности.')
sub('Как объяснить метрики')
bullet('MAE - средний абсолютный промах в денежных единицах; RMSE сильнее штрафует большие ошибки. 61,4% - относительное снижение MAE первой версии против baseline, не «точность 61,4%».')
bullet('Precision = TP/(TP+FP): сколько предупреждений подтвердилось. Recall = TP/(TP+FN): сколько наблюдавшихся событий найдено. Порог меняет оба показателя.')
bullet('Brier - ошибка вероятностного score относительно события 0/1; меньше лучше. ROC-AUC оценивает ранжирование, а не долю верных тревог и не калибровку.')
sub('Почему B6 не разрешил процент риска')
para('Всего четыре новых test-gap окна у трёх компаний: TP=2, FP=16, FN=2; precision 11,1%, recall 50%. Большинство остальных положительных окон уже начиналось с минуса. Такой выборки и качества недостаточно для надёжной продуктовой вероятности.')
sub('Ограничения доказательств')
para('Сентябрь уже просмотрен до исправленного повтора; нетронутым holdout его не называем. Окна одной компании зависимы. На короткой истории B4 из четырёх компаний улучшение не показано. B5: 268 общих окон; EWM, winsor и trend не прошли порог ≥5% улучшения MAE.',size=10)
source('B4: методика, числа и ограничения','evaluation/REPORT.md')
source('B5: сравнение методов','evaluation/B5-REPORT.md')
source('B6: решение по вероятности','evaluation/B6-REPORT.md')

head('6. Обновление: реальные данные и CatBoost')
para('**Важная поправка к персональной памятке.** После fetch origin/main = `cbe3f87dd1d7`. PR №55, №56 и №57 уже слиты. Памятка на 8168ec9 устарела в части статуса этих работ. Продуктовый default seasonal-guarded не заменён, числовая вероятность остаётся null.',size=10.4)
sub('MoneyVis: исследование регрессии потоков')
para('6 567 операций одного клиента, 2015-2022, без отрицательных остатков. Fit до 2020, validation 2021, test 2022. Это исходные денежные единицы, **не RUB**; ориентиры - repeat-week и weekday mean, а не полный продуктовый guarded engine.',size=10)
table(['Горизонт','CatBoost test MAE','Лучший ориентир test'],[
 ['7 дней','164,78','224,94'],['14 дней','479,89','481,59'],['30 дней','671,84','626,71'],
],[.20,.36,.44])
para('На test30 CatBoost хуже ориентира. Test содержит лишь 7 полных окон для 7 дней и по 6 для 14/30, один клиент. Это не доказательство переноса на МСП.',size=9.8,color=GRAY)
sub('Berka: классификация нового отрицательного EOD')
para('Цель - хотя бы один минус за 30 дней при неотрицательном opening. Fit до конца 1996, validation 1997, test 1998; выделены отдельные счета. Данные розничных счетов 1990-х не равны современным МСП.',size=10)
table(['Новые счета: 3 173 окна, 11 positive','v1','Кандидат v2'],[
 ['TP / FP / FN','6 / 14 / 5','6 / 15 / 5'],
 ['Precision / recall','30,0% / 54,5%','28,6% / 54,5%'],
 ['ROC-AUC','0,95659','0,97993'],
],[.54,.23,.23])
para('Рост ROC-AUC/AP v2 не улучшил предупреждения: те же находки и дополнительная ложная тревога. Калибратор follow-up не обучался: 8 positive при минимуме 10. Строгая политика выпуска не пройдена. `production_activated=false`, `probability_calibrated=false`, `release.allowed=false`.',size=9.8)
sub('Где взять честный отчёт для защиты')
para('После входа: GET `/api/v1/models/quality`. Это общая read-only offline-оценка исследовательских моделей; `applies_to_current_forecast=false`. Основные cohorts относятся к v1; v2 находится в evidence. 1998 уже просмотрен и обозначен retrospective, не новым holdout.',size=9.8)
source('MoneyVis и Berka: исходный отчёт','evaluation/REAL-DATA-REPORT.md')
source('Дополнительная проверка риска','evaluation/RISK-FOLLOWUP-REPORT.md')
source('Кандидат v2 и решение о выпуске','evaluation/RISK-CANDIDATE-V2-REPORT.md')
source('Контракт quality endpoint','specs/model-quality.md')

head('7. Рабочая карта Данила')
table(['Где смотреть','Что относится к твоему блоку'],[
 ['modules/contracts.py','ForecastInput, ForecastPointDTO, RiskSummary, ForecastResult, ScenarioChange'],
 ['forecasting/service.py; v2/service.py','Реестр pinned-моделей, default, quality и withheld probability'],
 ['forecasting/snapshot.py; core/forecast_input.py','Доступный на as_of frozen-вход и его сериализация; интеграционная граница'],
 ['forecasting/v2/incremental_*.py','История, дельты, bootstrap-grid и внутреннее состояние'],
 ['forecasting/legacy_v1/seasonal.py; scenarios.py','Закреплённая исходная математика, календарь и преобразование сценариев'],
 ['cash_gaps/service.py; pulse/frozen.py','Эпизоды, причины, preview и совпадение пульса с сохранённым p50'],
 ['evaluation/; tests/analytics/','Backtest, выбор метода, калибровка, real-data и проверки аналитики'],
],[.49,.51],size=8.8)
sub('Нужные API - префикс /api/v1')
para('POST `/companies/{company_id}/forecasts` → 202 и job/run; GET `/jobs/{job_id}`; GET `/forecasts/{id}` и `/explanations`; POST `/forecasts/{id}/scenarios`; GET `/forecasts/{scenario_id}/comparison`; GET `/forecasts/{id}/cash-gaps`; POST `/forecasts/{id}/cash-gap-preview`; GET `/forecasts/{id}/pulse`; GET `/models/quality`.',size=9.5)
sub('Что проверять до заявления об исправлении')
para('Одинаковый input/model/seed; отсутствие будущих признаков; планы без двойного счёта; денежные тождества; full/incremental совпадают; сценарий не меняет базу; качество не выдаётся за нулевой риск; метрики относятся к точному cohort/version.',size=10)
para('Чистая аналитика из backend: `uv sync --frozen`, затем `uv run pytest tests/analytics -q`. API/DB-тесты - только с отдельной уничтожаемой PostgreSQL `*_test` через CC_TEST_DATABASE_URL: fixtures делают TRUNCATE. Эти команды здесь не выполнялись.',size=9.8)
sub('Полные схемы - без сокращения')
para('Стр. 8: A02, все 4 участника и 11 сообщений расчёта. Стр. 9: A05, snapshot, quality, full/incremental. Стр. 10: A08, сценарии, разрывы и пульс. Все три схемы перенесены целиком из общего альбома; изменена лишь нумерация страниц.',size=10)
para('Источники: общая техдокументация на e8f93fc; персональная памятка Данила на 8168ec9 использована для определения зоны; новые отчёты прочитаны из origin/main cbe3f87. Авторство коммитов и новый runtime-прогон не устанавливались.',size=8.9,color=GRAY)
source('Исходные DTO','backend/app/modules/contracts.py')

c.save();buf.seek(0)
writer=PdfWriter();writer.append(PdfReader(buf))
for i,title in enumerate(['Твой технический участок','Вход, причинность и incremental','Кассовый разрыв и объяснения',
                          'Сценарии и финансовый пульс','Метрики B4/B5/B6','Реальные данные и CatBoost','Код, API и проверки']):
    writer.add_outline_item(str(i+1)+'. '+title,i)
atlas=PdfReader(ATLAS)
appendix=[(24,'A02. Полный жизненный цикл прогноза'),(29,'A05. Полный расчёт и incremental'),(32,'A08. Сценарии, кассовые разрывы и пульс')]
for i,(source_index,title) in enumerate(appendix,8):
    writer.add_page(atlas.pages[source_index])
    p=writer.pages[-1];pw=float(p.mediabox.width);ph=float(p.mediabox.height)
    overlay=io.BytesIO();oc=canvas.Canvas(overlay,pagesize=(pw,ph))
    oc.setFillColor(colors.white);oc.rect(pw-170,13,140,20,fill=1,stroke=0)
    oc.setFillColor(GRAY);oc.setFont('Body',9);oc.drawRightString(pw-40,22,f'{i} / 10')
    oc.save();overlay.seek(0);p.merge_page(PdfReader(overlay).pages[0])
    writer.add_outline_item(title,i-1)
writer.add_metadata({'/Title':'CashCast - техническая выжимка для Данила','/Author':'CashCast',
                     '/Subject':'Прогноз, кассовый разрыв, сценарии и проверка качества'})
with FINAL.open('wb') as f:writer.write(f)
r=PdfReader(FINAL);text='\n'.join(p.extract_text() or '' for p in r.pages)
assert len(r.pages)==10
for term in ['seasonal-guarded-2.0-w84','200','84','cbe3f87','8168ec9','61,4%','164,78','671,84','28,6%',
             'models/quality','applies_to_current_forecast=false','release.allowed=false','TRUNCATE','11 сообщений']:
    assert term in text,term
for source_index,target_index in [(24,7),(29,8),(32,9)]:
    original=atlas.pages[source_index].extract_text() or '';copied=r.pages[target_index].extract_text() or ''
    assert all(line in copied for line in original.splitlines()),source_index
manifest={'output':str(FINAL),'pages':len(r.pages),'source_diagrams':[25,30,33],
          'diagram_content':'all source text retained; no scaling or cropping',
          'source_main':SHA,'technical_base':BASE,'sha256':hashlib.sha256(FINAL.read_bytes()).hexdigest()}
(TMP/'danil-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(manifest,ensure_ascii=False,indent=2))
