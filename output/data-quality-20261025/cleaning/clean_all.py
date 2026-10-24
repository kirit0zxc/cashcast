"""Полный локальный аудит и консервативные производные копии без сторонних библиотек.

Никогда не печатает строки источника. Исходные архивы читаются без извлечения.
Производные идентификаторы — псевдонимы, а не гарантия анонимности.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile

BASE = Path(__file__).resolve().parents[3]
REPORT = BASE / 'output/data-quality-20261025/cleaning'
DERIVED = BASE / 'data/raw/quality-20261025'
INPUT = Path('C:/Users/Karp/Desktop/Hak-pos/colab')
DOWNLOADS = Path('C:/Users/Karp/Downloads')
VERSION = 'cashcast-conservative-cleaning-v1'
csv.field_size_limit(4_000_000)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def token(namespace, value):
    return hashlib.sha256((VERSION + '\0' + namespace + '\0' + value).encode()).hexdigest()[:24]


def row_digest(row):
    return hashlib.sha256(json.dumps(row, ensure_ascii=False, separators=(',', ':')).encode()).digest()


def minor(value):
    """Только точные сотые: никакого float и скрытого округления."""
    try:
        d = Decimal(value.strip())
    except (InvalidOperation, AttributeError):
        raise ValueError('invalid_money') from None
    if not d.is_finite() or d * 100 != (d * 100).to_integral_value():
        raise ValueError('nonfinite_or_subcent_money')
    return int(d * 100)


def valid_archive(path):
    """Проверяет пути, типы, шифрование и пределы ДО открытия любого члена."""
    z = zipfile.ZipFile(path)
    infos = z.infolist()
    if len(infos) > 10000 or sum(i.file_size for i in infos) > 2_000_000_000:
        z.close()
        raise ValueError('archive_limit')
    seen = set()
    for i in infos:
        p = PurePosixPath(i.filename.replace('\\', '/'))
        mode = i.external_attr >> 16
        if (p.is_absolute() or '..' in p.parts or ':' in i.filename or '\x00' in i.filename
            or i.filename in seen or stat.S_ISLNK(mode) or i.flag_bits & 1
            or i.file_size > 600_000_000 or i.file_size / max(1, i.compress_size) > 1000):
            z.close()
            raise ValueError('unsafe_archive_member')
        seen.add(i.filename)
    return z


def records(path, member=None, delimiter=','):
    """Читает все строки с проверкой прямоугольности; исключения не раскрывают данные."""
    if member:
        with valid_archive(path) as z, z.open(member) as stream:
            yield from parse_csv(io.TextIOWrapper(stream, encoding='utf-8-sig', newline=''), delimiter)
    else:
        with Path(path).open(encoding='utf-8-sig', newline='') as stream:
            yield from parse_csv(stream, delimiter)


def parse_csv(stream, delimiter):
    r = csv.reader(stream, delimiter=delimiter, strict=True)
    headers = next(r)
    if len(set(headers)) != len(headers):
        raise ValueError('duplicate_headers')
    for row_number, values in enumerate(r, 2):
        if len(values) != len(headers):
            yield row_number, None, headers
        else:
            yield row_number, dict(zip(headers, values)), headers


class Profile:
    def __init__(self, name):
        self.name = name
        self.rows = 0
        self.accepted = 0
        self.missing = Counter()
        self.none_literal = Counter()
        self.reasons = Counter()
        self.flags = Counter()
        self.fields = []
        self.money_in = Counter()
        self.money_out = Counter()
        self.low = None
        self.high = None
        self.quarantine = []

    def observe(self, row_number, row, fields):
        self.rows += 1
        self.fields = fields
        if row is None:
            self.reject(row_number, 'nonrectangular_row')
            return False
        for k, v in row.items():
            if not v.strip():
                self.missing[k] += 1
            if v.strip() in ('None', 'NULL', 'null', 'NA', 'N/A'):
                self.none_literal[k] += 1
        return True

    def reject(self, n, reason):
        self.reasons[reason] += 1
        # Только номер строки и причина, без содержимого и идентификаторов.
        self.quarantine.append((n, reason))

    def at(self, day):
        self.low = min(self.low, day) if self.low else day
        self.high = max(self.high, day) if self.high else day

    def result(self, **extra):
        return dict(dataset=self.name, scanned_rows=self.rows, full_scan=True,
                    accepted_rows=self.accepted, excluded_rows=self.rows-self.accepted,
                    exclusion_reasons=dict(self.reasons), flags=dict(self.flags),
                    columns=self.fields, blank_counts=dict(self.missing),
                    literal_missing_token_counts=dict(self.none_literal),
                    minimum_date=str(self.low) if self.low else None,
                    maximum_date=str(self.high) if self.high else None,
                    source_money_totals=dict(self.money_in), exported_money_totals=dict(self.money_out),
                    conservation_exact=self.money_in == self.money_out,
                    **extra)


def writer(name, fields):
    p = DERIVED / name
    f = p.open('w', encoding='utf-8', newline='')
    w = csv.writer(f, lineterminator='\n')
    w.writerow(fields)
    return f, w


def save(profile, **extra):
    result = profile.result(**extra)
    (REPORT / (profile.name + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    qf, qw = writer(profile.name + '_quarantine.csv', ['source_row_number', 'reason'])
    with qf:
        qw.writerows(profile.quarantine)
    print(json.dumps({'completed': profile.name, 'scanned_rows': profile.rows, 'accepted_rows': profile.accepted, 'excluded_rows': profile.rows-profile.accepted}), flush=True)
    return result


def participants():
    path = INPUT / 'cashflow_dataset_participants.zip'
    p = Profile('participants')
    seen, source_multiset = {}, Counter()
    daily = defaultdict(lambda: [0, 0, 0, set()])
    companies = set()
    f, w = writer('participants_transactions.csv', ['entity','transaction','date','currency','amount_minor','direction','balance_eod_minor','counterparty_missing','purpose_missing','source_row_number'])
    with f:
        for n, r, fields in records(path, 'all_operations.csv', ';'):
            if not p.observe(n, r, fields):
                continue
            dg = row_digest([r[x] for x in fields])
            source_multiset[dg] += 1
            try:
                if not r['company_id'] or not r['operation_id']:
                    raise ValueError('missing_primary_key')
                d = date.fromisoformat(r['operation_date'])
                a, b = minor(r['amount']), minor(r['balance_eod'])
                if a <= 0:
                    raise ValueError('nonpositive_amount')
                direction = {'Поступление':'in','Списание':'out'}.get(r['direction'])
                if direction is None:
                    raise ValueError('unknown_direction')
            except (ValueError, KeyError) as e:
                p.reject(n, str(e) if str(e) in {'missing_primary_key','nonpositive_amount','unknown_direction','invalid_money','nonfinite_or_subcent_money'} else 'invalid_date_or_schema')
                continue
            p.money_in[direction] += a
            key = (r['company_id'], r['operation_id'])
            if key in seen:
                reason = 'exact_duplicate_primary_key' if seen[key] == dg else 'conflicting_primary_key'
                p.reject(n, reason)
                # Ожидаемая сумма исключённой строки видна отдельно, без её содержания.
                p.flags['excluded_' + direction + '_minor'] += a
                continue
            seen[key] = dg
            entity = token('participants_entity', r['company_id'])
            transaction = token('participants_transaction', '\0'.join(key))
            companies.add(entity)
            item = daily[(entity, d)]
            item[0 if direction == 'in' else 1] += a
            item[2] += 1
            item[3].add(b)
            p.money_out[direction] += a
            p.accepted += 1
            p.at(d)
            w.writerow([entity, transaction, d, 'RUB', a, direction, b, int(not r['counterparty_inn']), int(not r['payment_purpose']), n])
    # Альтернативные statements проверяются полностью, но не включаются в сумму дважды.
    alt = Counter()
    alt_rows = 0
    with valid_archive(path) as z:
        members = sorted(i.filename for i in z.infolist() if i.filename.startswith('statements/') and i.filename.endswith('.csv'))
    for member in members:
        for n, r, fields in records(path, member, ';'):
            if r is None:
                raise ValueError('nonrectangular_alternative_statement')
            alt[row_digest([r[x] for x in fields])] += 1
            alt_rows += 1
    f, w = writer('participants_daily.csv', ['entity','date','currency','inflow_minor','outflow_minor','net_minor','transaction_count','observed_balance_minor','balance_observed','coverage','transition_reconciled','transition_residual_minor','previous_observed_gap_days','history_transaction_count_asof','available_at'])
    transitions = Counter()
    negative_companies = set()
    grid_rows = 0
    residual_sum = 0
    for entity in sorted(companies):
        dates = sorted(d for e,d in daily if e == entity)
        previous_balance = previous_day = None
        history_count = 0
        for offset in range((dates[-1]-dates[0]).days+1):
            day = dates[0] + timedelta(days=offset)
            a,b,count,balances = daily.get((entity,day), [0,0,0,set()])
            history_count += count
            observed = len(balances) == 1
            balance = next(iter(balances)) if observed else ''
            residual = gap = reconciled = ''
            if len(balances) > 1:
                transitions['conflicting_balance_days'] += 1
            if observed:
                if balance < 0:
                    negative_companies.add(entity)
                if previous_balance is not None:
                    residual = balance - previous_balance - a + b
                    reconciled = int(residual == 0)
                    gap = (day-previous_day).days
                    transitions['checked'] += 1
                    transitions['reconciled' if reconciled else 'unreconciled'] += 1
                    residual_sum += residual
                previous_balance, previous_day = balance,day
            w.writerow([entity, day,'RUB',a,b,a-b,count,balance,int(observed), 'observed_transactions' if count else 'no_rows_unknown',reconciled,residual,gap,history_count,day])
            grid_rows += 1
    f.close()
    metadata = Profile('participants_companies')
    for n,r,fields in records(path,'companies.csv',';'):
        if metadata.observe(n,r,fields):
            metadata.accepted += 1
    save(metadata, used_as_model_features=False, reason='last date and total counts expose future; direct identifiers excluded')
    return save(p, synthetic=True, currency='RUB', currency_basis='Russian case amounts interpreted as rubles; source has no currency column', entities=len(companies), daily_rows=grid_rows,
                alternative_representation_rows=alt_rows, alternative_representation_equal_multiset=source_multiset==alt,
                alternative_representation_removed_from_combined_count=alt_rows, balance_transitions=dict(transitions),
                transition_residual_sum_minor=residual_sum, companies_with_observed_negative_balance=len(negative_companies),
                missing_labels='No reference category or obligation labels in source; not imputed',
                modeling_contract='Only features available_at <= as_of; reconciliation is known on current endpoint, never back-propagated into gaps. Blank balance != zero. No-row daily flows describe recorded transactions, completeness unknown.')


def nn5():
    p = Profile('nn5')
    path = INPUT / 'nn5_daily_dataset_with_missing_values.zip'
    f,w = writer('nn5_daily.csv',['series','date','value','observed','available_at'])
    vf,vw = writer('nn5_values.csv',['series']+[f't{i}' for i in range(791)])
    mf,mw = writer('nn5_observed_mask.csv',['series']+[f't{i}' for i in range(791)])
    lengths = Counter()
    starts = Counter()
    total = missing = zeros = negative = 0
    exact = Counter()
    with f,vf,mf,valid_archive(path) as z,z.open('nn5_daily_dataset_with_missing_values.tsf') as raw:
        stream = io.TextIOWrapper(raw,encoding='utf-8-sig')
        data_started = False
        for n,line in enumerate(stream,1):
            line=line.strip()
            if line.lower() == '@data':
                data_started=True
                continue
            if not data_started or not line or line.startswith('#'):
                continue
            p.rows += 1
            name,start,values=line.split(':',2)
            start=datetime.strptime(start,'%Y-%m-%d %H-%M-%S').date()
            entity=token('nn5',name)
            values=values.split(',')
            lengths[len(values)] += 1
            starts[str(start)] += 1
            canonical=[]
            masks=[]
            for offset,v in enumerate(values):
                total += 1
                observed = v != '?'
                d=start+timedelta(days=offset)
                p.at(d)
                if not observed:
                    missing += 1
                    value='NaN'
                else:
                    value=Decimal(v)
                    if not value.is_finite():
                        raise ValueError('nn5_nonfinite_observed_value')
                    if value < 0:
                        negative += 1
                    if value == 0:
                        zeros += 1
                    exact['raw_observed_sum'] += value
                    exact['exported_observed_sum'] += value
                    value=str(value)
                canonical.append(value)
                masks.append(int(observed))
                w.writerow([entity,d,value,int(observed),d])
            vw.writerow([entity]+canonical)
            mw.writerow([entity]+masks)
            p.accepted += 1
    return save(p, observational_unit='ATM daily withdrawal series, no account balance',series_lengths=dict(lengths),starts=dict(starts), cells=total,missing_cells=missing,true_zero_cells=zeros,negative_observed_cells=negative,
                nominal_unit='source withdrawal units; currency/scale not stated in TSF; not converted to cents',observed_sum=str(exact['raw_observed_sum']),exported_observed_sum=str(exact['exported_observed_sum']),
                no_imputation=True, arrays='Rows retain source series order; columns t0..t790; NaN and explicit 0/1 mask; dates in nn5_daily.csv')


def berka():
    p=Profile('berka')
    path=INPUT/'berka-trans.zip'
    seen={}
    daily=defaultdict(lambda:[0,0,0])
    f,w=writer('berka_transactions.csv',['account','transaction','date','currency','amount_minor','direction','balance_after_minor','operation_label','symbol_label','source_row_number'])
    negatives=0
    with f:
        for n,r,fields in records(path,'trans.asc',';'):
            if not p.observe(n,r,fields):continue
            try:
                d=datetime.strptime(r['date'],'%y%m%d').date()
                a,b=minor(r['amount']),minor(r['balance'])
                dr={'PRIJEM':'in','VYDAJ':'out','VYBER':'out'}.get(r['type'])
                if dr is None:raise ValueError('unknown_direction')
                if a < 0:raise ValueError('negative_unsigned_amount')
                if not r['trans_id'] or not r['account_id']:raise ValueError('missing_primary_key')
            except ValueError as e:
                reason=str(e) if str(e) in ('unknown_direction','negative_unsigned_amount','missing_primary_key','invalid_money','nonfinite_or_subcent_money') else 'invalid_date'
                p.reject(n,reason);continue
            p.money_in[dr]+=a
            dg=row_digest([r[x] for x in fields])
            key=r['trans_id']
            if key in seen:
                p.reject(n,'exact_duplicate_primary_key' if seen[key]==dg else 'conflicting_primary_key');continue
            seen[key]=dg
            account=token('berka_account',r['account_id'])
            daily[(account,d)][0 if dr=='in' else 1]+=a
            daily[(account,d)][2]+=1
            p.money_out[dr]+=a
            p.accepted+=1
            p.at(d)
            negatives+=b<0
            w.writerow([account,token('berka_transaction',key),d,'CZK',a,dr,b,token('berka_operation',r['operation']) if r['operation'] else '',token('berka_symbol',r['k_symbol']) if r['k_symbol'] else '',n])
    f,w=writer('berka_daily.csv',['account','date','currency','inflow_minor','outflow_minor','net_minor','transaction_count','balance_eod_minor','balance_status','available_at'])
    with f:
        for (account,d),(a,b,c) in sorted(daily.items()):
            # Порядок внутри дня не задан: последний остаток нельзя определять порядком CSV.
            w.writerow([account,d,'CZK',a,b,a-b,c,'','unknown_intraday_order',d])
    return save(p,accounts=len({a for a,d in daily}),daily_rows=len(daily),negative_balance_rows=negatives,
                currency='CZK',currency_basis='Berka Czech financial transaction dataset; supplied CSV lacks currency field',balance='per-transaction source balance retained; no asserted EOD without within-day order',category='Original operation/symbol labels pseudonymized, never filled when blank')


def bpi():
    p=Profile('bpi2019')
    seen={}
    cases=set()
    f,w=writer('bpi2019_events.csv',['event','case','timestamp','currency','cumulative_net_worth_minor','activity','source_row_number'])
    negative=0
    with f:
        for n,r,fields in records(INPUT/'BPIChallenge2019CSV.zip','BPI_Challenge_2019.csv'):
            if not p.observe(n,r,fields):continue
            try:
                ts=datetime.strptime(r['event time:timestamp'],'%d-%m-%Y %H:%M:%S.%f')
                a=minor(r['event Cumulative net worth (EUR)'])
                if not r['eventID ']:raise ValueError('missing_primary_key')
            except ValueError as e:
                p.reject(n,str(e) if str(e) in ('missing_primary_key','invalid_money','nonfinite_or_subcent_money') else 'invalid_timestamp');continue
            key=r['eventID ']
            dg=row_digest([r[x] for x in fields])
            if key in seen:
                # Повторные process events сохраняются: это аудит, не основание для удаления.
                p.flags['exact_duplicate_event_key' if seen[key]==dg else 'conflicting_event_key']+=1
            else:seen[key]=dg
            case=token('bpi_case',r['case concept:name'])
            cases.add(case)
            p.at(ts.date());p.accepted+=1
            p.money_in['cumulative_observations_EUR_minor']+=a
            p.money_out['cumulative_observations_EUR_minor']+=a
            negative+=a<0
            w.writerow([token('bpi_event',key),case,ts.isoformat(),'EUR',a,token('bpi_activity',r['event concept:name']),n])
    return save(p,cases=len(cases),negative_cumulative_value_rows=negative,semantics='Procurement process event log; cumulative net worth is an event attribute, NOT payment or account balance. Never sum as cashflow; total only checks export conservation.',repeated_events='All parseable events retained, including repeated keys; no inferred cashflow or fictitious balance')


UK_NUMERIC=['Average time to pay','% Invoices paid within 30 days','% Invoices paid between 31 and 60 days','% Invoices paid later than 60 days','% Invoices not paid within agreed terms','% Invoices not paid due to dispute','Shortest (or only) standard payment period','Longest standard payment period','Maximum contractual payment period']
UK_MONEY=['Total value invoices paid within 30 days','Total value invoices paid between 31 and 60 days','Total value invoices paid later than 60 days','Total value invoices paid later than agreed terms']


def uk():
    p=Profile('uk_payment_practices')
    seen={}
    entities=set()
    f,w=writer('uk_payment_practices_reports.csv',['report','entity','start_date','end_date','available_at','qualifying_contracts','payments_made']+['metric_'+str(i) for i in range(len(UK_NUMERIC))]+['reported_value_minor_'+str(i) for i in range(len(UK_MONEY))]+['source_row_number'])
    money_present=Counter()
    numeric_errors=Counter()
    condition_missing=Counter()
    with f:
        for n,r,fields in records(INPUT/'uk-payment-practices.zip','payment-practices.csv'):
            if not p.observe(n,r,fields):continue
            try:
                start=date.fromisoformat(r['Start date']);end=date.fromisoformat(r['End date']);filing=date.fromisoformat(r['Filing date'])
                if not r['Report Id']:raise ValueError('missing_primary_key')
            except ValueError as e:
                p.reject(n,'missing_primary_key' if str(e)=='missing_primary_key' else 'invalid_date');continue
            dg=row_digest([r[x] for x in fields]);key=r['Report Id']
            if key in seen:p.flags['exact_duplicate_report_key' if seen[key]==dg else 'conflicting_report_key']+=1
            else:seen[key]=dg
            nums=[]
            for k in UK_NUMERIC:
                value=r[k].strip()
                if value in ('','None','null','NULL','NA','N/A'):
                    nums.append('');condition_missing[k+'|payments_'+r['Payments made in reporting period']]+=1;continue
                try:
                    v=Decimal(value)
                    if not v.is_finite():raise ValueError
                    nums.append(str(v))
                    if ('%' in k and not 0<=v<=100) or v<0:p.flags['out_of_range_'+k]+=1
                except (ValueError,InvalidOperation):
                    nums.append('');numeric_errors[k]+=1
            amounts=[]
            for k in UK_MONEY:
                value=r[k].strip()
                if value in ('','None','null','NULL','NA','N/A'):
                    amounts.append('');continue
                try:
                    v=minor(value);amounts.append(v);money_present[k]+=1
                    p.money_in[k]+=v;p.money_out[k]+=v
                except ValueError:
                    amounts.append('');numeric_errors[k]+=1
            if end<start:p.flags['end_before_start']+=1
            if filing<end:p.flags['filing_before_period_end']+=1
            company=token('uk_company',r['Company number']) if r['Company number'] else ''
            entities.add(company)
            w.writerow([token('uk_report',key),company,start,end,filing,r['Qualifying contracts in reporting period'],r['Payments made in reporting period']]+nums+amounts+[n])
            p.at(filing);p.accepted+=1
    return save(p,entities=len(entities-{''}),numeric_parse_errors=dict(numeric_errors),numeric_missing_by_payments_made=dict(condition_missing),monetary_field_present_counts=dict(money_present),
                numeric_columns=UK_NUMERIC,monetary_columns=UK_MONEY,currency='unspecified_in_supplied_csv',semantics='Company reporting-period metrics, not daily bank cashflow; revisions retained. Filing date is availability, not period start.',missingness='Blank/None retained missing; conditional blanks reported by payments_made; cannot prove all are structural. Numeric parse failures remain missing and counted; no imputed labels.')


def open_bank():
    p=Profile('open_bank')
    seen={}
    dates=Counter()
    values=[]
    f,w=writer('open_bank_transactions.csv',['transaction','date','currency','debit_minor','credit_minor','balance_minor','debit_observed','credit_observed','category','category_observed','source_row_number'])
    with f:
        for n,r,fields in records(INPUT/'open-bank-transactions.csv'):
            if not p.observe(n,r,fields):continue
            try:
                d=datetime.strptime(r['Transaction Date'],'%d/%m/%Y').date()
                b=minor(r['Balance'])
                debit=minor(r['Debit Amount']) if r['Debit Amount'].strip() else None
                credit=minor(r['Credit Amount']) if r['Credit Amount'].strip() else None
                if not r['Transaction Number']:raise ValueError('missing_primary_key')
            except ValueError as e:
                p.reject(n,str(e) if str(e) in ('missing_primary_key','invalid_money','nonfinite_or_subcent_money') else 'invalid_date');continue
            dg=row_digest([r[x] for x in fields]);key=r['Transaction Number']
            if key in seen:
                # Без доказательства уникальности ID коллизия не уничтожает запись.
                p.flags['exact_duplicate_key' if seen[key]==dg else 'conflicting_key']+=1
            else:seen[key]=dg
            for k,v in [('debit',debit),('credit',credit)]:
                if v is not None:
                    p.money_in[k]+=v;p.money_out[k]+=v
                    if v<0:p.flags['negative_'+k]+=1
            if debit is not None and credit is not None:p.flags['both_sides_present']+=1
            if debit is None and credit is None:p.flags['both_sides_missing']+=1
            values.append((d,debit,credit,b));dates[d]+=1
            p.at(d);p.accepted+=1
            w.writerow([token('open_bank_transaction',key),d,'UNSPECIFIED',debit if debit is not None else '',credit if credit is not None else '',b,int(debit is not None),int(credit is not None),token('open_bank_category',r['Category']) if r['Category'] else '',int(bool(r['Category'])),n])
    # Не делаем остаток EOD по неустановленному account_id и порядку внутри дня.
    chronological=all(values[i][0]<=values[i+1][0] for i in range(len(values)-1))
    reverse=all(values[i][0]>=values[i+1][0] for i in range(len(values)-1))
    return save(p,date_format='DD/MM/YYYY verified by day components >12',currency='UNSPECIFIED',account_id='absent; no assumption of one account',chronological_source_order=chronological,reverse_chronological_source_order=reverse,
                semantic_missingness='One debit/credit side blank is consistent with structural absence, but blank retained with observed mask. Missing category and transaction type not imputed.',balance_reconciliation='Not asserted: account and currency metadata absent and no within-day ordering contract')


def inventory():
    """Инвентаризация источников, включая архивы с кодом/картинками, без их исполнения."""
    paths=sorted(INPUT.iterdir())
    paths += [DOWNLOADS/'Сравнение моделей CashCast.zip']
    paths += sorted(Path('C:/Users/Karp/Desktop/Hak-pos/model-compare-report').glob('*'))
    duplicate=DOWNLOADS/'uk-payment-practices/payment-practices.csv'
    if duplicate.is_file():paths.append(duplicate)
    out=[]
    for path in paths:
        if not path.is_file():continue
        entry=dict(source_alias=path.name,size_bytes=path.stat().st_size,sha256=sha(path))
        if path.suffix.lower()=='.zip':
            with valid_archive(path) as z:
                entry['members']=[dict(name=i.filename,size=i.file_size,compressed=i.compress_size,crc32=f'{i.CRC:08x}') for i in z.infolist()]
                if path.name=='uk-payment-practices.zip':
                    h=hashlib.sha256()
                    with z.open('payment-practices.csv') as f:
                        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
                    entry['csv_sha256']=h.hexdigest()
        entry['_path']=path
        out.append(entry)
    return out


def run(selected):
    DERIVED.mkdir(parents=True,exist_ok=True)
    REPORT.mkdir(parents=True,exist_ok=True)
    before=inventory()
    (REPORT/'source_inventory.json').write_text(json.dumps([{k:v for k,v in x.items() if k!='_path'} for x in before],ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summaries={}
    funcs={'participants':participants,'nn5':nn5,'berka':berka,'bpi2019':bpi,'uk':uk,'open_bank':open_bank}
    for name in selected:
        summaries[name]=funcs[name]()
    unchanged=all(sha(x['_path'])==x['sha256'] for x in before)
    artifacts=[dict(name=p.name,size_bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(DERIVED.glob('*.csv'))]
    uk_arch=next(x for x in before if x['source_alias']=='uk-payment-practices.zip')
    uk_copies=[x for x in before if x['source_alias']=='payment-practices.csv']
    manifest=dict(version=VERSION,python=sys.version.split()[0],selected_datasets=selected,raw_originals_sha256_unchanged_after_run=unchanged,
                  uk_download_copy_byte_identical=bool(uk_copies) and all(x['sha256']==uk_arch['csv_sha256'] for x in uk_copies),
                  outputs=artifacts,limitations=['Pseudonyms are deterministic; dates/amounts remain sensitive. Derived CSVs stay gitignored.','No learned imputation, rescaling, outlier deletion, fabricated transactions, or cross-dataset/currency joins.','RUB/CZK assumptions marked; open-bank/UK currency unspecified.','Balance reconciliation only diagnoses observed intervals and is not a license to backfill missing transactions.'])
    (REPORT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if not unchanged:raise RuntimeError('raw_changed')
    return summaries


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--datasets',nargs='+',choices=['participants','nn5','berka','bpi2019','uk','open_bank'],default=['participants','nn5','berka','bpi2019','uk','open_bank'])
    args=ap.parse_args()
    run(args.datasets)
