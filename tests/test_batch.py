"""Offline budget/batch orchestration checks; all prices/trades in fixtures are synthetic."""
import contextlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import batch_pilot as batch
from chain import RPCError
from hardforks import hardfork_for_range
from market import timestamp
import test_pilot
from pilot import build_report


class BatchTests(unittest.TestCase):
    def test_preview_is_offline_and_displays_estimate_before_any_pilot(self):
        with tempfile.TemporaryDirectory() as d, patch.object(batch.pilot,'main') as run, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(batch.main(['--quota-dir',d]),0)
            run.assert_not_called()
            self.assertIn('6973056',out.getvalue())
            self.assertIn('8716320',out.getvalue())
            self.assertEqual(list(pathlib.Path(d).iterdir()),[])

    def test_invalid_dates_limits_and_transition_days_stop_before_pilot(self):
        cases=[['--dates','2025-06-01,2025-06-01'],['--max-total-cu','10000001'],
               ['--dates','2025-05-07'],['--dates','2025-12-03'],['--dates','2026-03-01'],
               ['--max-cu-per-day','0'],['--every-n-blocks','0']]
        for args in cases:
            with self.subTest(args=args),patch.object(batch.pilot,'main') as run:
                with self.assertRaises(ValueError):batch.main(args+['--run'])
                run.assert_not_called()

    def test_execution_rules_for_approved_dates(self):
        for date,expected in [('2025-03-10','cancun'),('2025-08-22','prague'),('2026-01-24','osaka'),('2026-02-05','osaka')]:
            self.assertEqual(hardfork_for_range(timestamp(date),timestamp(date)+86400),expected)

    def report(self):
        m,rows,v=test_pilot.PilotTests().inputs()
        return build_report(m,rows,v,dict(cumulative=1,pilot=1,days30=30,days90=90))

    def test_error_stops_later_dates_and_does_not_treat_them_as_zero(self):
        with tempfile.TemporaryDirectory() as d:
            folder=pathlib.Path(d)/'output'
            with patch.object(batch.pilot,'main',side_effect=RPCError('synthetic upstream failure')) as run,contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                code=batch.main(['--dates','2025-06-19,2025-07-29','--quota-dir',d,'--output',str(folder),'--run'])
            self.assertEqual(code,2);self.assertEqual(run.call_count,1)
            data=json.loads((folder/'batch.json').read_text())
            self.assertEqual([r['status'] for r in data['daily']],['INCOMPLETE','NOT_RUN'])
            self.assertIsNone(data['daily'][1]['opportunities'])
            self.assertEqual(data['totals']['complete_days'],0)

    def test_aggregation_counts_dates_but_does_not_sum_equity(self):
        with tempfile.TemporaryDirectory() as d:
            folder=pathlib.Path(d)/'output';reports=[self.report(),self.report()]
            with patch.object(batch.pilot,'main',side_effect=reports) as run,contextlib.redirect_stdout(io.StringIO()):
                code=batch.main(['--dates','2025-06-19,2025-07-29','--quota-dir',d,'--output',str(folder),'--run'])
            self.assertEqual(code,0);self.assertEqual(run.call_count,2)
            data=json.loads((folder/'batch.json').read_text())
            self.assertEqual(data['totals']['complete_days'],2)
            self.assertEqual(data['totals']['opportunities']['A'],2)
            self.assertNotIn('final_nok',data['totals'])
            self.assertIn('NOT one portfolio',data['warning'])
            for call in run.call_args_list:
                argv=call.args[0]
                self.assertEqual(argv[argv.index('--max-cu')+1],'10000000')
                self.assertEqual(argv[argv.index('--max-cu-per-day')+1],'1200000')
                self.assertIn('--verify-replay',argv)


if __name__=='__main__':unittest.main()
