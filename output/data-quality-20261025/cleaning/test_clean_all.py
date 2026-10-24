"""Независимые проверки инвариантов преобразования и фактических экспортов."""
import csv
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location('clean_all',ROOT/'clean_all.py')
clean=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(clean)


class Rules(unittest.TestCase):
    def test_money_precision_and_invalid_values(self):
        self.assertEqual(clean.minor('9007199254740993.01'),900719925474099301)
        self.assertEqual(clean.minor('-0.01'),-1)
        self.assertEqual(clean.minor('1.2300'),123)
        for x in ['0.001','NaN','Infinity','broken']:
            with self.assertRaises(ValueError):clean.minor(x)

    def test_digest_distinguishes_conflicting_duplicate_and_multiplicity(self):
        first=['a','1.00','2020-01-01']
        conflict=['a','2.00','2020-01-01']
        self.assertNotEqual(clean.row_digest(first),clean.row_digest(conflict))
        self.assertNotEqual(Counter([clean.row_digest(first)]),Counter([clean.row_digest(first)]*2))

    def test_archive_blocks_traversal_duplicate_and_absolute(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as td:
            for member in ['../escape.csv','/absolute.csv','C:/drive.csv','x/../../escape.csv']:
                path=Path(td)/'bad.zip'
                with zipfile.ZipFile(path,'w') as z:z.writestr(member,'header\n')
                with self.assertRaises(ValueError):clean.valid_archive(path)
            path=Path(td)/'safe.zip'
            with zipfile.ZipFile(path,'w') as z:z.writestr('table.csv','a,b\n1,2\n')
            with clean.valid_archive(path) as z:self.assertEqual(len(z.infolist()),1)

    def test_nonrectangular_row_is_not_silently_shifted(self):
        import io
        result=list(clean.parse_csv(io.StringIO('a,b\n1,2,3\n4,5\n'),','))
        self.assertIsNone(result[0][1])
        self.assertEqual(result[1][1],{'a':'4','b':'5'})


class ActualExports(unittest.TestCase):
    @unittest.skipUnless((clean.DERIVED/'participants_transactions.csv').is_file(),'export not yet built')
    def test_participants_export_money_and_daily_grid_conservation(self):
        totals=Counter()
        daily_totals=Counter()
        txn_count=0
        with (clean.DERIVED/'participants_transactions.csv').open(encoding='utf-8',newline='') as f:
            for row in csv.DictReader(f):
                totals[row['direction']]+=int(row['amount_minor']);txn_count+=1
        self.assertEqual(txn_count,222420)
        self.assertEqual(totals,Counter({'in':2102815774429,'out':2082354140731}))
        previous={}
        breaks=0
        unobserved=0
        with (clean.DERIVED/'participants_daily.csv').open(encoding='utf-8',newline='') as f:
            for row in csv.DictReader(f):
                daily_totals['in']+=int(row['inflow_minor']);daily_totals['out']+=int(row['outflow_minor'])
                self.assertEqual(row['available_at'],row['date'])
                self.assertEqual(int(row['net_minor']),int(row['inflow_minor'])-int(row['outflow_minor']))
                if row['balance_observed']=='0':
                    unobserved+=1
                    self.assertEqual(row['observed_balance_minor'],'')
                    self.assertEqual(row['transition_reconciled'],'')
                if row['transition_reconciled']=='0':breaks+=1
                entity=row['entity']
                current_count=int(row['history_transaction_count_asof'])
                self.assertEqual(current_count,previous.get(entity,0)+int(row['transaction_count']))
                previous[entity]=current_count
        self.assertEqual(totals,daily_totals)
        self.assertEqual(sum(previous.values()),txn_count)
        self.assertEqual(breaks,99)
        self.assertGreater(unobserved,0)

    @unittest.skipUnless((clean.DERIVED/'nn5_daily.csv').is_file(),'export not yet built')
    def test_nn5_missing_is_not_zero_and_masks_match_arrays(self):
        missing=zeros=cells=0
        total=Decimal(0)
        with (clean.DERIVED/'nn5_daily.csv').open(encoding='utf-8',newline='') as f:
            for row in csv.DictReader(f):
                cells+=1
                self.assertEqual(row['available_at'],row['date'])
                if row['observed']=='0':
                    self.assertEqual(row['value'],'NaN');missing+=1
                else:
                    value=Decimal(row['value']);self.assertTrue(value.is_finite())
                    total+=value;zeros+=value==0
        self.assertEqual((cells,missing,zeros),(87801,1677,419))
        self.assertEqual(total,Decimal('1588603.1744242498226072'))
        with (clean.DERIVED/'nn5_values.csv').open(encoding='utf-8',newline='') as f,(clean.DERIVED/'nn5_observed_mask.csv').open(encoding='utf-8',newline='') as g:
            vr,mr=csv.reader(f),csv.reader(g)
            self.assertEqual(next(vr),next(mr))
            rows=0
            for vals,masks in zip(vr,mr,strict=True):
                self.assertEqual(vals[0],masks[0]);self.assertEqual(len(vals),792)
                self.assertEqual([int(v!='NaN') for v in vals[1:]],[int(m) for m in masks[1:]])
                rows+=1
            self.assertEqual(rows,111)


if __name__=='__main__':unittest.main()
