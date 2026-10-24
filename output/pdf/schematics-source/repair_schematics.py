from __future__ import annotations

import ast
import hashlib
import io
import json
import math
import re
import textwrap
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream
from pypdf.annotations import Link
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, A3, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

ROOT = Path(__file__).resolve().parents[3]
TMP = ROOT / 'tmp/pdfs'
TMP.mkdir(parents=True, exist_ok=True)
OUT = ROOT / 'output/pdf'
SOURCE = OUT / 'CashCast-project-and-pitch.pdf'
FINAL = OUT / 'CashCast-project-and-pitch-complete-schematics.pdf'
TECH = ROOT / 'docs/technical-documentation.md'
BASE = 'e8f93fc5c9db4dc8f7d3535a0d8b9dde47505615'
INK = colors.HexColor('#173744')
TEAL = colors.HexColor('#147D89')
PALE = colors.HexColor('#EEF6F7')
GRAY = colors.HexColor('#65767D')
RULE = colors.HexColor('#D5E3E7')
RED = colors.HexColor('#9A4B42')

for name,file in [('Body','calibri.ttf'),('Bold','calibrib.ttf'),('Mono','consola.ttf')]:
    pdfmetrics.registerFont(TTFont(name,str(Path(r'C:\Windows\Fonts')/file)))
pdfmetrics.registerFontFamily('Body',normal='Body',bold='Bold',italic='Body',boldItalic='Bold')

def norm(s):
    return s.translate(str.maketrans({'—':'-','–':'-','‑':'-','\u00a0':' ','\u202f':' '}))

def paragraph(c,text,x,top,w,size=11,color=INK,bold=False):
    import html
    p=Paragraph(html.escape(norm(text)).replace('\n','<br/>'),ParagraphStyle(
        'p',fontName='Bold' if bold else 'Body',fontSize=size,leading=size*1.3,textColor=color))
    _,h=p.wrap(w,10000)
    p.drawOn(c,x,top-h)
    return h

def label(c,text,x,y,w=240,size=10,color=INK):
    import html
    p=Paragraph(html.escape(norm(text)),ParagraphStyle('edge',fontName='Body',fontSize=size,
                leading=size*1.22,textColor=color,alignment=1))
    _,h=p.wrap(w,10000)
    c.setFillColor(colors.white); c.roundRect(x-w/2-3,y-h/2-3,w+6,h+6,3,fill=1,stroke=0)
    p.drawOn(c,x-w/2,y-h/2)

def arrow(c,points,text=None,where=None,width=220,dashed=False,color=TEAL,size=10):
    c.setStrokeColor(color); c.setFillColor(color); c.setLineWidth(1.2)
    c.setDash(4,3) if dashed else c.setDash()
    path=c.beginPath(); path.moveTo(*points[0])
    for p in points[1:]:path.lineTo(*p)
    c.drawPath(path); c.setDash()
    x,y=points[-1]; a=math.atan2(y-points[-2][1],x-points[-2][0])
    p=c.beginPath(); p.moveTo(x,y)
    p.lineTo(x-7*math.cos(a-.4),y-7*math.sin(a-.4));p.lineTo(x-7*math.cos(a+.4),y-7*math.sin(a+.4));p.close()
    c.drawPath(p,fill=1,stroke=0)
    if text:
        if where is None:where=((points[0][0]+x)/2,(points[0][1]+y)/2+14)
        label(c,text,*where,w=width,size=size)

def node(c,x,y,w,h,title,body='',size=11,fill=PALE):
    c.setFillColor(fill);c.setStrokeColor(RULE);c.roundRect(x,y,w,h,7,fill=1,stroke=1)
    pstyle=ParagraphStyle('node-title',fontName='Bold',fontSize=size,leading=size*1.25,textColor=INK,alignment=1)
    import html
    p=Paragraph(html.escape(norm(title)),pstyle);_,ph=p.wrap(w-18,h)
    if body:
        p.drawOn(c,x+9,y+h-12-ph)
        bh=paragraph(c,body,x+10,y+h-20-ph,w-20,size-1)
        assert ph+bh+30<=h,(title,ph,bh,h)
    else:p.drawOn(c,x+9,y+(h-ph)/2)
    return (x,y,w,h)

def process(c,items,x,top,w,step=113,h=84,size=11):
    for i,(title,body) in enumerate(items):
        y=top-i*step-h
        node(c,x,y,w,h,title,body,size)
        if i:arrow(c,[(x+w/2,y+h+step-h),(x+w/2,y+h)])
    return top-len(items)*step

def table(c,headers,rows,x,top,widths,rowh=27,size=9.4):
    total=sum(widths)
    c.setFillColor(INK);c.rect(x,top-rowh,total,rowh,fill=1,stroke=0)
    xx=x
    for title,w in zip(headers,widths):paragraph(c,title,xx+6,top-6,w-12,size,colors.white,True);xx+=w
    top-=rowh
    for r,row in enumerate(rows):
        c.setFillColor(PALE if r%2 else colors.white);c.rect(x,top-rowh,total,rowh,fill=1,stroke=0)
        xx=x
        for value,w in zip(row,widths):
            ht=paragraph(c,str(value),xx+6,top-5,w-12,size)
            assert ht<=rowh-7,(value,ht,rowh)
            xx+=w
        c.setStrokeColor(RULE);c.setLineWidth(.4);c.line(x,top-rowh,x+total,top-rowh)
        top-=rowh
    return top

# Считываем полную структуру FK из AST, не импортируя приложение и не подключаясь к БД.
entities=[]; fks=[]; all_fields={}
for path in sorted((ROOT/'backend/app/core/models').glob('*.py')):
    tree=ast.parse(path.read_text(encoding='utf-8'))
    for cls in [n for n in tree.body if isinstance(n,ast.ClassDef)]:
        tn=next((n.value.value for n in cls.body if isinstance(n,ast.Assign)
                 and any(isinstance(t,ast.Name) and t.id=='__tablename__' for t in n.targets)
                 and isinstance(n.value,ast.Constant)),None)
        if not tn:continue
        entities.append(tn);fields=[];pk=[]
        for stmt in cls.body:
            if not isinstance(stmt,ast.AnnAssign) or not isinstance(stmt.target,ast.Name):continue
            col=stmt.target.id;fields.append(col)
            if isinstance(stmt.value,ast.Call):
                if isinstance(stmt.value.func,ast.Name) and stmt.value.func.id=='uuid_pk':pk.append(col)
                if any(k.arg=='primary_key' and isinstance(k.value,ast.Constant) and k.value.value for k in stmt.value.keywords):pk.append(col)
                for call in ast.walk(stmt.value):
                    if isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='ForeignKey':
                        target=call.args[0].value
                        deletion=next((k.value.value for k in call.keywords if k.arg=='ondelete'),'NO ACTION')
                        nullable=('None' in ast.unparse(stmt.annotation))
                        fks.append({'source':tn,'column':col,'target':target.split('.')[0],
                                    'target_column':target.split('.')[1],'nullable':nullable,'ondelete':deletion})
        all_fields[tn]={'fields':fields,'pk':pk,'source':str(path.relative_to(ROOT)).replace('\\','/')}
entities.sort();fks.sort(key=lambda a:(a['source'],a['column']))
assert len(entities)==16
for i,fk in enumerate(fks,1):fk['id']=f'F{i:02}'
registry_pages=math.ceil(len(fks)/19)
names=[('A01','Архитектура: все компоненты, направления и подписи'),
       ('A02','Жизненный цикл прогноза: все 11 сообщений'),
       ('A03','Данные: все 16 таблиц и все внешние ключи')]
names += [(f'A03.{i+1}','Полный реестр внешних ключей') for i in range(registry_pages)]
names += [('A04','Выписки, обязательства и план-факт'),('A05','Прогноз: полный расчёт и incremental'),
          ('A06','Очередь: статусы, повтор и восстановление'),('A07','Кабинет: все маршруты и обновления'),
          ('A08','Сценарии, кассовые разрывы и пульс'),('A09','Ассистент: чтение, предложение и подтверждение'),
          ('A10','Compose: запуск, сеть и хранение')]
pages={id:24+i for i,(id,_) in enumerate(names)}
TOTAL=23+len(names)
atlas=io.BytesIO();c=canvas.Canvas(atlas,pagesize=landscape(A3),pageCompression=1)
atlas_index=0

def header(id,title,source,small=False):
    global atlas_index
    c.setPageSize(landscape(A3)); w,h=landscape(A3)
    c.setFillColor(TEAL);c.setFont('Bold',10);c.drawString(40,h-28,'CASHCAST / ПОЛНЫЙ АЛЬБОМ СХЕМ')
    c.setFillColor(GRAY);c.setFont('Body',9);c.drawRightString(w-40,h-28,'24.10.2026 • база e8f93fc')
    paragraph(c,f'{id}. {title}',40,h-49,w-80,21,bold=True)
    paragraph(c,source,40,h-84,w-80,9,GRAY)
    c.setStrokeColor(RULE);c.line(40,37,w-40,37)
    c.setFont('Body',9);c.setFillColor(GRAY)
    c.drawString(40,22,'Все подписи и ветви сохраняются. Полнота исходных схем сверена с Mermaid; новые виды - с кодом.')
    c.drawRightString(w-40,22,f'{23+atlas_index} / {TOTAL}')
    atlas_index+=1
    return w,h

def finish():c.showPage()

w,h=header('IV','Проверка полноты и навигация','Исходники: docs/technical-documentation.md; specs/architecture.md; ORM; API, jobs, forecasting, assistant, frontend и Compose.')
paragraph(c,'В прежнем PDF обе исходные схемы были сокращены вручную. Архитектура потеряла подписи связей и части названий; диаграмма прогноза объединила отдельные действия. Сокращённые рисунки удалены из основной части. Их места теперь ведут к полноразмерным схемам A01 и A02.',40,715,w-80,12)
table(c,['Проверяемый оригинал','Что сохранено в новой версии','Полная схема'],[
    ['flowchart LR / архитектура','7 компонентов; 6 направленных связей; все 3 подписи связей',f'A01, стр. {pages["A01"]}'],
    ['sequenceDiagram / прогноз','4 участника; 11 раздельных сообщений; полный текст каждого сообщения',f'A02, стр. {pages["A02"]}'],
    ['Модель данных','16 таблиц; '+str(len(fks))+' FK из AST; nullable и ondelete каждого FK',f'A03, стр. {pages["A03"]}'],
],40,635,[270,650,190],rowh=38,size=11)
rows=[[id,title,str(pages[id])] for id,title in names]
table(c,['Схема','Содержание','Страница'],rows,40,440,[100,920,90],rowh=23,size=10)
paragraph(c,'Альбом дополняет техническую документацию на фиксированном commit. После fetch origin/main уже содержит 8168ec9 (без изменения топологии этих схем); база основного текста сохранена, чтобы не смешивать версии. Проверялась полнота представления, без запуска приложения и тестовой БД.',40,90,w-80,9,GRAY)
finish()

# A01: точные семь узлов и шесть связей оригинального Mermaid.
w,h=header('A01',names[0][1],'Источник: docs/technical-documentation.md, flowchart LR; полный состав соответствует присланному скриншоту.')
node(c,42,565,175,66,'Браузер: React SPA',size=13)
node(c,365,565,145,66,'web: nginx',size=13)
node(c,704,565,145,66,'api: FastAPI',size=13)
node(c,973,565,177,66,'OpenRouter / DeepSeek',size=12)
arrow(c,[(217,598),(365,598)],'HTTP, cookie, CSRF',(291,621),width=140,size=11)
arrow(c,[(510,598),(704,598)],'/api/v1',(606,621),width=110,size=12)
arrow(c,[(849,598),(973,598)],'необязательный чат',(910,650),width=180,dashed=True,size=11)
# Цилиндр БД: полная версия СУБД остаётся в подписи.
c.setFillColor(PALE);c.setStrokeColor(TEAL);c.rect(945,352,180,80,fill=1,stroke=1)
c.ellipse(945,416,1125,448,fill=1,stroke=1);c.arc(945,336,1125,368,180,180)
paragraph(c,'PostgreSQL 16',966,397,138,14,bold=True)
node(c,470,353,185,68,'worker: Python',size=13)
node(c,650,180,238,72,'migrate: Alembic и demo seed',size=12)
arrow(c,[(777,565),(777,488),(1035,488),(1035,448)])
arrow(c,[(655,387),(945,387)],'jobs, lease, результаты',(796,414),width=250,size=12)
arrow(c,[(888,216),(918,216),(918,368),(945,368)])
paragraph(c,'Направления без сокращений',42,281,370,15,bold=True)
paragraph(c,'Браузер → web → api → PostgreSQL. Worker → PostgreSQL. Migrate → PostgreSQL. API → OpenRouter / DeepSeek - необязательный внешний чат. Ключ провайдера находится только у API.',42,249,390,12)
paragraph(c,'Очередь и результаты находятся в PostgreSQL; прямой вызов worker из API не изображается как реальная сетевая связь. API ставит job в БД, worker читает очередь. Дополнение запуска и портов - A10.',42,133,1080,11,GRAY)
finish()

# A02: сообщения берутся из Markdown буквально, без объединения.
md=TECH.read_text(encoding='utf-8')
seq=re.search(r'```mermaid\n(sequenceDiagram[\s\S]*?)\n```',md).group(1)
messages=[]
for line in seq.splitlines():
    m=re.match(r'\s*(\w+)(--?>>)(\w+): (.*)',line)
    if m:messages.append(m.groups())
assert len(messages)==11
w,h=header('A02',names[1][1],'Источник: исходный sequenceDiagram; COMMIT, GET job и GET forecast показаны отдельными сообщениями.')
xs={'UI':85,'API':375,'DB':705,'WK':1065}
for key,name in [('UI','Кабинет'),('API','FastAPI'),('DB','PostgreSQL'),('WK','Worker')]:
    node(c,xs[key]-65,671,130,40,name,size=12)
    c.setStrokeColor(RULE);c.setDash(3,3);c.line(xs[key],103,xs[key],671);c.setDash()
for i,(a,kind,b,text) in enumerate(messages):
    y=640-i*46
    if a==b:
        arrow(c,[(xs[a],y),(xs[a]+65,y),(xs[a]+65,y-16),(xs[a],y-16)],dashed=kind=='-->>')
        label(c,f'{i+1}. {text}',xs[a]-125,y+9,w=260,size=10)
    else:
        arrow(c,[(xs[a],y),(xs[b],y)],dashed=kind=='-->>')
        label(c,f'{i+1}. {text}',(xs[a]+xs[b])/2,y+12,w=abs(xs[a]-xs[b])-10,size=10.2)
paragraph(c,'Порядок 1-11 и полный текст сохранены. Пунктир обозначает ответы. Дополнительная детализация retry/lease - A06; ветвление full/incremental - A05.',40,82,w-80,10,GRAY)
finish()

# A03: полная матрица FK без скрытых рёбер, плюс исчерпывающий реестр.
w,h=header('A03','Все таблицы и все внешние ключи','Источник: AST backend/app/core/models/*.py. Строка - дочерняя таблица, столбец - родительская. Fxx - уникальный FK; все Fxx раскрыты на следующих страницах.')
ids={n:i+1 for i,n in enumerate(entities)}
x0=390;y0=670;cell=30
for j in range(16):
    paragraph(c,str(j+1),x0+j*cell+8,y0+22,25,10,bold=True)
for i,n in enumerate(entities):
    y=y0-(i+1)*cell
    paragraph(c,f'{i+1:02}. {n}',42,y+22,338,10,bold=True)
    for j,parent in enumerate(entities):
        c.setFillColor(PALE if i%2 else colors.white);c.setStrokeColor(RULE);c.rect(x0+j*cell,y,cell,cell,fill=1,stroke=1)
        hits=[f['id'][1:] for f in fks if f['source']==n and f['target']==parent]
        if hits:paragraph(c,','.join(hits),x0+j*cell+3,y+20,cell-5,8,TEAL,True)
paragraph(c,'Как читать',930,664,210,14,bold=True)
paragraph(c,f'16 таблиц\n{len(fks)} внешних ключей\n\nЧисло в клетке - номер Fxx из реестра. Направление: source.column → target.column. Два FK одной пары таблиц не объединяются.\n\nМатрица включает self-FK forecast_run.base_forecast_id.\n\nСвязь job → forecast_run находится в JSON payload и не является FK. Checkpoint и provenance также не превращаются в выдуманные таблицы.',930,630,210,11)
paragraph(c,'Первичные ключи',42,163,650,13,bold=True)
paragraph(c,'company_member: (company_id, user_id); forecast_point: (forecast_run_id, point_date). Остальные 14 таблиц: id. Иные поля, уникальности и проверки описаны в основной модели данных; внешние ключи перечислены полностью.',42,137,1060,11)
finish()
for part in range(registry_pages):
    w,h=header(f'A03.{part+1}','Полный реестр FK: '+str(part*19+1)+'-'+str(min((part+1)*19,len(fks))),
               'Никакие FK не опущены. Nullable - из ORM-аннотации; ON DELETE - из ForeignKey. В реестре только реальные ограничения БД.')
    rows=[[f['id'],f['source']+'.'+f['column'],f['target']+'.'+f['target_column'],'да' if f['nullable'] else 'нет',f['ondelete']]
          for f in fks[part*19:(part+1)*19]]
    table(c,['ID','Дочернее поле','Родительское поле','Nullable','ON DELETE'],rows,40,705,[55,425,390,85,155],rowh=29,size=10)
    paragraph(c,'Служебные связи вне FK: job.payload.forecast_run_id; forecast_run.details._incremental_state; ссылки provenance/source_ref. Они описаны отдельно, не подменяют ссылочную целостность PostgreSQL.',40,101,1100,11,GRAY)
    finish()

w,h=header('A04','Выписки, обязательства и план-факт','Источники: modules/imports; modules/planning/sources.py и matching.py; modules/integration/plan_fact.py и manual_confirmation.py.')
process(c,[('Выписка: POST imports','account_id + mapping + file; размер, кодировка, деньги, направления, RUB'),
 ('Preview выписки','Сводка и ошибки; исходные bytes в statement_import; повтор account+SHA возвращает прежний импорт'),
 ('Явный POST commit','Account lock; повторный разбор; проверка всех конфликтов до вставки'),
 ('Атомарная запись','bank_transaction + daily_balance + категории; ручная категория сохраняется')],40,701,325,step=117,h=87)
process(c,[('Обязательства: POST obligation-imports','source_name + as_of + файл; даты, суммы, provenance, namespace внешнего ID'),
 ('Preview обязательств','Нормализованные items/errors/stats; исходный CSV не хранится; ошибки запрещают частичный commit'),
 ('Явный POST commit','Account lock; тот же документ не сбрасывает оплату/отмену; изменённый ID → 409 SOURCE_ID_CONFLICT'),
 ('Атомарная запись','planned_event: amount, remaining, available_at, source_ref, provenance, source_payload')],420,701,325,step=117,h=87)
process(c,[('GET plan-fact: чтение','Исторические guards; shared lock; предложения не являются оплатой'),
 ('Matcher и бюджет','active plans × доступные операции ≤100000; дата/направление/identity; суммы с учётом аллокаций'),
 ('Запись только явным действием','POST safe reconcile или confirm выбранной полной/частичной суммы; неоднозначность остаётся proposal'),
 ('Одна транзакция','Account lock; проверка остатков плана и операции; confirmed match + remaining; двойной расход запрещён')],800,701,350,step=117,h=87)
paragraph(c,'Развилки и ошибки сохранены',40,203,1110,14,bold=True)
paragraph(c,'Ошибки preview исправляются до commit. Конфликт операции или документа откатывает весь пакет. Идентичный commit возвращает прежнюю сводку. Исторически неоднозначное состояние плана → 409; превышение бюджета → 422 без записей. Commit импорта не enqueue прогноз: обычный кабинет отправляет отдельный POST после успеха.',40,172,1110,12)
finish()

w,h=header('A05','Прогноз: снимок, качество, full и incremental','Источники: api/v1/forecasts.py; forecasting/snapshot.py; v2/service.py, quality.py, incremental_*; jobs/incremental.py.')
process(c,[('1. HTTP и целевой счёт','Сессия/CSRF/owner; RUB; as_of ≤ today UTC; horizon 1-180; ресурсные лимиты'),
 ('2. Account lock и план-факт','На today UTC - safe auto-confirm; исторический срез только читает; все аллокации учтены'),
 ('3. Frozen input / dedupe','Операции/EOD ≤ as_of; планы available_at ≤ as_of; категории/регулярности; opening; data_version'),
 ('4. Run + job, COMMIT → 202','Закреплены model_version и seed. Повтор идентичного входа возвращает тот же run/job')],40,707,330,step=116,h=90)
process(c,[('5. Worker: decode pinned input','get_forecast_service(run.model_version); неизвестная версия - явная ошибка'),
 ('6. Quality guard','Сверка EOD/потоков, свежесть opening; окно после несверки; plan_only / point_only / empirical'),
 ('7. Выбор checkpoint','Не сценарий; до 8 успешных баз той же компании/счёта/model/seed/horizon; old as_of ≤ new'),
 ('8. Контроль состояния','Версия ledger-update-v2, context, checksum. Нет/повреждено/несовместимо → FULL')],430,707,330,step=116,h=90)
node(c,820,535,152,170,'9a. FULL','Первый запуск, несовместимый seed/horizon/model, сценарий или отсутствие пригодного состояния',11)
node(c,998,535,152,170,'9b. INCREMENTAL','Изменённые операции/категории/recurrence buckets; дневные дельты; reuse/RNG по допустимым блокам',11)
node(c,820,396,330,105,'10. Общая финальная часть','Полное календарное сопоставление; траектории + opening; квантили, объяснения, daily components',11)
node(c,820,265,330,100,'11. Атомарный результат','forecast_point + details + checkpoint; probability=null, risk.available=false; job/run succeeded',11)
arrow(c,[(896,535),(896,501)])
arrow(c,[(1074,535),(1074,501)])
arrow(c,[(985,396),(985,365)])
arrow(c,[(370,275),(401,275),(401,662),(430,662)])
arrow(c,[(760,275),(790,275),(790,730),(896,730),(896,705)],'нет совместимого состояния',(872,724),width=180,size=9)
arrow(c,[(790,730),(1074,730),(1074,705)],'совместимое состояние есть',(1064,724),width=180,size=9)
paragraph(c,'Совместимость и ограничения',40,198,1110,14,bold=True)
paragraph(c,'Новые факты, поздние факты, категории, планы и движение даты вперёд могут использовать incremental. При смене as_of пересматриваются группы; при смене состава bootstrap-блоков сетка создаётся заново. Сценарии - полный расчёт. API по-прежнему готовит полный snapshot: весь запрос не объявляется O(delta). Старый успешный результат не переписывается.',40,168,1110,12)
paragraph(c,'Итоговая диагностика: calculation.mode, reason, source_forecast_id, categorized/reused_transactions, recurrence_buckets_recomputed, daily_aggregates_changed, trajectory_values_updated и bootstrap_paths_generated.',40,100,1110,11,GRAY)
finish()

w,h=header('A06','Очередь: все статусы и ветви восстановления','Источники: jobs/queue.py, worker.py, recovery.py и handlers.py. Внешние побочные эффекты не покрываются транзакцией PostgreSQL.')
node(c,70,536,240,100,'pending','run_after ≤ now; attempts < max_attempts; dedupe_key уникален',13)
node(c,470,536,250,100,'running','Claim: attempts+1; worker_id; lease. Claim COMMIT, затем handler lock.',13)
node(c,900,536,235,100,'succeeded','Точки, run и job фиксируются атомарно. lease очищается.',13)
node(c,470,260,250,100,'failed','Permanent input/model error, исчерпание attempts или reaper.',13)
arrow(c,[(310,590),(470,590)],'FOR UPDATE SKIP LOCKED',(390,667),width=210,size=11)
arrow(c,[(720,590),(900,590)],'handler успешно + COMMIT',(810,667),width=220,size=11)
arrow(c,[(595,536),(595,360)],'Permanent input/model, исчерпание attempts или reaper → failed',(728,420),width=225,size=11)
arrow(c,[(470,556),(390,556),(390,485),(190,485),(190,536)],'Retryable, попытки остались: pending + 30 сек',(250,449),width=350,size=11)
arrow(c,[(470,300),(190,300),(190,536)],'Явный owner POST: только allowlist transient; max_attempts = attempts + 3',(186,387),width=280,size=11)
arrow(c,[(720,555),(788,555),(788,510),(692,510),(692,536)],'Процесс умер: lease истёк, попытки остались → повторный claim',(990,471),width=300,size=11)
paragraph(c,'Дополнительные обязательные условия',50,207,1090,15,bold=True)
paragraph(c,'Живой handler удерживает row lock, поэтому истечение lease само по себе не дублирует исполнение. Старый worker сверяет locked_by и attempt до записи. Reaper (до 100 строк, SKIP LOCKED) закрывает running с истёкшим lease и исчерпанными attempts; код lease_expired_attempts_exhausted. ForecastRun.failed/finished_at синхронизируются; успешный результат не стирается.',50,174,1090,12)
paragraph(c,'Повтор POST не возобновляет ошибки данных, неизвестной модели и произвольные неклассифицированные ошибки. IDs, input и seed сохраняются; номер attempts не сбрасывается. Lease по умолчанию 300 сек, исходный max_attempts 3, poll 1 сек.',50,101,1090,11,GRAY)
finish()

w,h=header('A07','Кабинет: все маршруты и автоматические обновления','Источники: frontend/src/app/router.tsx, AppShell.tsx, account-context.tsx, forecast-controller.tsx; features/assistant/chat.ts.')
node(c,40,578,1110,108,'Сессия → выбранные company/account → права owner/viewer',
     'GET auth/me; AppShell и AccountProvider. Смена пользователя очищает query cache; смена компании/счёта сбрасывает локальные формы/выбранный расчёт/чат. History API, Back/Forward и прямые URL; неизвестный путь → /overview.',13)
routes=re.findall(r'path: "([^"]+)", title: "([^"]+)"',(ROOT/'frontend/src/app/router.tsx').read_text(encoding='utf-8'))
assert len(routes)==9
for i,(route,title) in enumerate(routes):
    col=i%3;row=i//3
    node(c,40+col*380,443-row*103,350,76,route,title,12)
arrow(c,[(595,578),(595,559)])
c.setStrokeColor(TEAL);c.setLineWidth(1.2);c.line(25,559,785,559)
for col in range(3):
    bx=25+col*380
    c.line(bx,559,bx,275)
    for row in range(3):arrow(c,[(bx,481-row*103),(40+col*380,481-row*103)])
table(c,['Успешное действие обычного кабинета','Срез нового POST forecast','Поведение'],[
 ['Commit выписки','preview.period_end','Новый обычный базовый прогноз'],
 ['План / обязательство / сверка','today UTC','Новый обычный базовый прогноз'],
 ['Ручная категория','Текущий выбранный as_of','Новый обычный базовый прогноз'],
 ['History / reload / смена даты / раздела','Автоматического POST нет','Чтение; дата требует явного запуска'],
 ['Действие ассистента','Собственное явное подтверждение','Запись помечает график устаревшим; propose_forecast открывает созданный job'],
 ],40,220,[440,240,430],rowh=24,size=10)
paragraph(c,'Viewer не запускает автоматическую запись. Poll job каждые 1500 мс до succeeded/failed; поздние ответы отбрасываются; terminal failed не порождает бесконечные POST. Никакой push-подписки на изменения стороннего API-клиента нет.',40,66,1110,9.4,GRAY)
finish()

w,h=header('A08','Сохранённый результат: сценарии, разрывы и пульс','Источники: api/v1/scenarios в forecasts.py; cash_gaps/service.py; pulse/frozen.py, service.py. Все ветви сохраняют исходную базу.')
node(c,40,618,1110,74,'Успешный frozen forecast_run + input_snapshot + forecast_point',
     'Старые записи без snapshot читаются с ограничениями; для зависимых вычислений требуется новая база.',13)
arrow(c,[(210,618),(210,560)]);arrow(c,[(595,618),(595,560)]);arrow(c,[(980,618),(980,560)])
process(c,[('Обычный сценарий: POST scenarios','1-50 changes; отдельный job/run; та же закреплённая модель; сценарий считается full'),
 ('Все четыре типа','delay_event; reduce_irregular_inflow; add_expense; increase_recurring'),
 ('GET comparison','Сохранённые base/scenario; проверка даты, горизонта, model/data/seed. Другой seed исключает paired comparison')],40,560,340,step=116,h=91)
process(c,[('GET cash-gaps','Opening на as_of + дневные p50; existing/new эпизоды; ноль - восстановление; причины минимума'),
 ('POST cash-gap-preview','1-3 действия: delay или financing. Перенос закупки требует согласия; защищённые расходы не переносятся'),
 ('Ответ без записи','Медианная гипотеза; стоимость/возврат/долг за горизонтом; нет job и новой вероятности; viewer + CSRF разрешены')],425,560,340,step=116,h=91)
process(c,[('GET pulse','Точная сохранённая p50-кривая и frozen вход, не live-таблицы; buffer_minor опционален, 0 допустим'),
 ('Все продуктовые направления','Касса/подушка/действия; аудит расходов; B2B-концентрация и клиентский stress'),
 ('Гипотезы с ограничениями','Техническая поправка к p50 не является выручкой; peers до 30.09.2026 отключены; экономии пересекаются')],810,560,340,step=116,h=91)
paragraph(c,'Общие границы',40,171,1110,15,bold=True)
paragraph(c,'Факты и реальные планы не меняются. Числовая вероятность нового разрыва недоступна: null не равен 0%. Финансирование - сценарий с раскрытой стоимостью, не предложение банка. Риск дневной, внутридневная ликвидность не определяется. Подходящая рекомендация пульса не означает согласие контрагента на отсрочку.',40,139,1110,12)
finish()

w,h=header('A09','Ассистент: чтение, предложение и явное решение','Источники: modules/assistant/contracts.py, service.py, gateway.py, actions.py; api/v1/assistant.py. Право подтверждения модели не передаётся.')
node(c,40,614,340,90,'1. Чат выбранного company/account','Сессия + CSRF; request_id и input hash; daily quota; разрешённые tools; ключ только API',11)
node(c,40,445,340,105,'2a. Read-tools → ответ без финансовой записи','Gateway вызывает те же ручки; tool projection обезличивается; CSV исходником не отправляется. Ветка чтения не требует propose.',11)
node(c,430,614,340,90,'2b. propose_*','Только owner; типизированные аргументы и target; неизменяемая запись AssistantAction',11)
node(c,430,445,340,105,'3. Карточка пользователю','Точные аргументы, user/company/account, fingerprint и expires_at +15 минут. Текстовое «да» не подтверждает',11)
node(c,40,267,340,105,'4. Отдельная кнопка / actions POST','decision confirm или cancel; сессия/CSRF; блокировка предложения; проверка владельца и owner',11)
node(c,430,267,340,105,'5. Повтор / отмена → конечный ответ','confirmed → сохранённый result; cancelled → без изменения; cancel → status cancelled',11)
node(c,40,115,340,105,'6. Проверки нового confirm','Истёк срок → 409 expired. Account lock; fingerprint изменился → 409 stale. Требуется новое предложение',11)
node(c,430,115,340,105,'7. Выполнение и COMMIT','Gateway execute + confirmed + result в одной транзакции; ошибка → rollback. Job открывается без второго POST',11)
arrow(c,[(210,614),(210,550)],'чтение',(210,581),width=100,size=10)
arrow(c,[(380,659),(430,659)],'предложить изменение',(404,731),width=200,size=10)
arrow(c,[(600,614),(600,550)])
arrow(c,[(600,445),(600,408),(210,408),(210,372)],'только отдельное решение пользователя',(405,408),width=300,size=10)
arrow(c,[(380,320),(430,320)])
arrow(c,[(210,267),(210,220)],'новое confirm',(210,243),width=150,size=10)
arrow(c,[(380,168),(430,168)],'валидно',(404,232),width=100,size=10)
paragraph(c,'Все восемь записывающих предложений',825,704,320,16,bold=True)
writes=['propose_forecast','propose_scenario','propose_create_plan','propose_update_plan','propose_category','propose_reconcile','propose_match','propose_commit_import']
for i,name in enumerate(writes):paragraph(c,f'{i+1}. {name}',825,663-i*31,320,12)
paragraph(c,'Другие разрешённые пути',825,377,320,14,bold=True)
paragraph(c,'GET assistant/status; POST assistant/chat; POST assistant/uploads (preview); POST actions/{id}. Viewer может читать, но не предлагать и не подтверждать финансовую запись. Произвольные SQL, URL и исполнение кода модели недоступны.',825,347,320,11)
paragraph(c,'Свободный текст отправляется провайдеру. Очистка видимой истории не удаляет серверные turn/action. Числа берутся из серверных данных; модель не подтверждает действия.',40,87,1110,10,GRAY)
finish()

w,h=header('A10','Compose: все зависимости запуска, сеть и хранение','Источник: infra/docker-compose.yml, Dockerfile, nginx.conf, migrate_and_seed.sh. Сплошные стрелки - все шесть depends_on; сеть дана отдельной полной таблицей.')
node(c,40,485,210,105,'postgres:16.10-alpine','pg_isready healthcheck; БД, очередь, результаты и bytes выписок',12)
node(c,430,485,250,105,'migrate: one-shot','alembic upgrade head → optional demo seed. Успех с кодом 0; restart: no',12)
node(c,900,620,250,100,'api: FastAPI','backend Dockerfile; внутренний 8000; ключ OpenRouter только у API',12)
node(c,900,400,250,100,'worker: Python','backend Dockerfile; python -m app.worker; без ключа LLM',12)
node(c,900,200,250,100,'web: nginx','Статика SPA, /api/ proxy, DNS resolve; единственный публичный bind',12)
arrow(c,[(250,537),(430,537)],'postgres: service_healthy',(340,548),width=175,size=10)
arrow(c,[(250,565),(320,565),(320,670),(900,670)],'postgres: service_healthy',(605,698),width=235,size=10)
arrow(c,[(250,510),(300,510),(300,450),(900,450)],'postgres: service_healthy',(600,470),width=235,size=10)
arrow(c,[(680,560),(770,560),(770,645),(900,645)],'migrate: service_completed_successfully',(780,603),width=250,size=10)
arrow(c,[(555,485),(555,420),(900,420)],'migrate: service_completed_successfully',(735,394),width=280,size=10)
arrow(c,[(1150,670),(1171,670),(1171,250),(1150,250)],'api: service_started',(1030,335),width=200,size=10)
table(c,['Сетевая / файловая связь','Полная спецификация'],[
 ['Браузер → web','127.0.0.1:${WEB_PORT:-8080}:80; HTTP, cookie, CSRF'],
 ['web → api','/api/v1 через upstream api:8000; Docker DNS resolve'],
 ['api → postgres','CC_DATABASE_URL; внутренний postgres:5432'],
 ['worker → postgres','CC_DATABASE_URL; очередь, lease, результаты; внутренний 5432'],
 ['migrate → postgres','CC_DATABASE_URL; Alembic и demo seed; внутренний 5432'],
 ['api → OpenRouter / DeepSeek','Необязательный HTTPS-чат; секрет не передаётся worker/frontend'],
 ['postgres → pgdata','/var/lib/postgresql/data; постоянный volume; down -v удаляет данные'],
 ],40,365,[285,545],rowh=25,size=10)
paragraph(c,'Restart и учётные данные',40,130,790,13,bold=True)
paragraph(c,'postgres, api, worker, web: unless-stopped. API и PostgreSQL не публикуют порты наружу. Seed создаёт отсутствующего пользователя; изменение CC_DEMO_PASSWORD не меняет пароль уже созданной записи.',40,101,1080,11)
finish()
c.save();atlas.seek(0)

# Удаляем именно контейнеры двух сокращённых Drawing, а не маскируем их белой заливкой.
reader=PdfReader(SOURCE);writer=PdfWriter();writer.clone_document_from_reader(reader)
removed={}
for page_index,cy,id,bottom,height in [(7,308.3898,'A01',308.3898,174),(11,444.8898,'A02',444.8898,292)]:
    page=writer.pages[page_index];stream=ContentStream(page.get_contents(),writer);ops=stream.operations
    depth=0;start=0;target=[]
    for i,(args,op) in enumerate(ops):
        if op==b'q':
            if depth==0:start=i
            depth+=1
        elif op==b'Q':
            depth-=1
            if depth==0:
                b=ops[start:i+1];cms=[a for a,o in b if o==b'cm']
                if cms and len(cms[0])==6 and abs(float(cms[0][4])-46)<.01 and abs(float(cms[0][5])-cy)<.02:
                    target.append((start,i))
    assert len(target)==1,target
    a,b=target[0];stream.operations=ops[:a]+ops[b+1:];page.replace_contents(stream);removed[id]=b-a+1
    overlay=io.BytesIO();oc=canvas.Canvas(overlay,pagesize=A4)
    oc.setFillColor(PALE);oc.setStrokeColor(RULE);oc.roundRect(46,bottom+14,503,height-28,8,fill=1,stroke=1)
    paragraph(oc,f'{id}. Полная схема перенесена на отдельную страницу',66,bottom+height-18,458,15,bold=True)
    msg=('Все 7 компонентов, 6 связей и 3 подписи сохранены. Схема дана крупно, без сокращений.' if id=='A01' else
         'Все 4 участника и 11 сообщений сохранены раздельно, включая COMMIT и оба GET-запроса.')
    paragraph(oc,msg,66,bottom+height-55,458,11)
    paragraph(oc,f'Открыть полную схему: стр. {pages[id]}. Альбом и карта полноты: стр. 23.',66,bottom+43,458,12,TEAL,True)
    oc.save();overlay.seek(0);page.merge_page(PdfReader(overlay).pages[0])
    writer.add_annotation(page_index,Link(rect=(46,bottom+14,549,bottom+height-14),target_page_index=pages[id]-1))

atlas_reader=PdfReader(atlas)
assert len(atlas_reader.pages)==1+len(names)
writer.append(atlas_reader,import_outline=False)
parent=writer.add_outline_item('IV. Полный альбом схем и проверка полноты',22)
for id,title in names:writer.add_outline_item(id+'. '+title,pages[id]-1,parent=parent)
# Ссылка на альбом в свободной нижней части оглавления, без сдвига остальных страниц.
toc_overlay=io.BytesIO();tc=canvas.Canvas(toc_overlay,pagesize=A4)
paragraph(tc,'IV. Полный альбом схем и проверка полноты',46,205,455,12,TEAL,True)
paragraph(tc,f'Архитектура; 11 сообщений расчёта; 16 таблиц и {len(fks)} FK; импорт, очередь, incremental, кабинет, сценарии, ассистент и Compose. Полная навигация - стр. 23.',46,179,455,10)
tc.save();toc_overlay.seek(0);writer.pages[1].merge_page(PdfReader(toc_overlay).pages[0])
writer.add_annotation(1,Link(rect=(46,142,548,210),target_page_index=22))
writer.add_metadata({'/Title':'CashCast: проект, защита и полный альбом схем','/Author':'CashCast',
                     '/Subject':'Полнота схем: 7 узлов / 6 связей; 11 сообщений; все ORM FK'})
with FINAL.open('wb') as f:writer.write(f)

check=PdfReader(FINAL);text='\n'.join(p.extract_text() or '' for p in check.pages)
compact=lambda s:re.sub(r'\s+','',norm(s))
full=compact(text)
for text_label in ['Браузер: React SPA','web: nginx','api: FastAPI','PostgreSQL 16','worker: Python',
                   'migrate: Alembic и demo seed','OpenRouter / DeepSeek','HTTP, cookie, CSRF','/api/v1',
                   'jobs, lease, результаты','необязательный чат']:
    assert compact(text_label) in full,text_label
for a,kind,b,msg in messages:assert compact(msg) in full,msg
for n in entities:assert n in text,n
for fk in fks:assert compact(fk['source']+'.'+fk['column']) in full,fk
for route,title in routes:assert route in text,route
assert len(check.pages)==TOTAL,(len(check.pages),TOTAL)
for i in range(22):
    if i not in (1,7,11):
        assert check.pages[i].get_contents().get_data()==reader.pages[i].get_contents().get_data(),i+1
manifest={'output':str(FINAL),'pages':TOTAL,'architecture_nodes':7,'architecture_edges':6,
          'architecture_edge_labels':3,'sequence_participants':4,'sequence_messages':11,
          'database_tables':len(entities),'foreign_keys':len(fks),'routes':len(routes),
          'schema_pages':pages,'removed_drawing_operations':removed,
          'sha256':hashlib.sha256(FINAL.read_bytes()).hexdigest()}
(TMP/'schema-audit.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
(TMP/'foreign-keys.json').write_text(json.dumps(fks,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(manifest,ensure_ascii=False,indent=2))
