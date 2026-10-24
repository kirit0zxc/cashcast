"""Подтверждение не должно удалять прежние тревоги или читать поздние ответы."""
import unittest

from .confirm_extra import ConfirmExtra


class ConfirmTests(unittest.TestCase):
    def test_original_warning_never_removed(self):
        row={'risk18':True,'current':0.,'scores':{'rolling_all':0.}}
        for gate in ConfirmExtra.GATES:self.assertEqual(ConfirmExtra.flags([row],gate),[True])

    def test_only_extra_signal_needs_confirmation(self):
        row={'risk18':False,'current':.1,'scores':{'rolling_all':.04}}
        self.assertEqual(ConfirmExtra.flags([row],0.),[True])
        self.assertEqual(ConfirmExtra.flags([row],.25),[False])

    def test_late_selection_rejected(self):
        with self.assertRaises(ValueError):ConfirmExtra.choose([{'cutoff':'2026-08-31'}])


if __name__=='__main__':unittest.main()
