"""Synthetic fixtures only: never historical observations or a profit claim."""
import copy
import json
import pathlib
import tempfile
import unittest

from test_backtest import fixture
from pilot import build_report, load_rows, markdown


class PilotTests(unittest.TestCase):
    def inputs(self):
        row, c, manifest = fixture()
        row = copy.deepcopy(row)
        row.update(block=100, selection='evaluated', candidates=[c])
        manifest.update(first=100, last=101, complete=True, start='2025-07-01',
                        end_exclusive='2025-07-02', every_n_blocks=60)
        boundary = dict(row, candidates=[])
        return manifest, [row, dict(block=101, selection='sampling_skipped')], dict(initial=boundary, final=boundary)

    def test_duplicate_sizes_do_not_inflate_opportunities_or_competition(self):
        manifest, rows, valuations = self.inputs()
        rows[0]['candidates'][0]['competition']['same_route_cycle_txs'] = ['0xsynthetic']
        rows[0]['candidates'].append(copy.deepcopy(rows[0]['candidates'][0]))
        report = build_report(manifest, rows, valuations, dict(cumulative=1, pilot=1, days30=30, days90=90))
        self.assertEqual(report['raw_opportunities']['A'], dict(route_block_opportunities=1, competitor_proxy=1))
        self.assertEqual(report['selected_blocks'], 1)
        self.assertTrue(all(r['counts'].get('wins', 0) == 0 for r in report['sensitivity']))
        self.assertEqual(len(report['sensitivity']), 16)

    def test_no_selected_blocks_still_reports_no_arbitrage_and_exposes_hold(self):
        manifest, rows, valuations = self.inputs()
        rows[0] = dict(block=100, selection='no_prior_swap')
        valuations['final'] = copy.deepcopy(valuations['final'])
        valuations['final']['snapshot']['eth_usd'] *= 2
        report = build_report(manifest, rows, valuations, dict(cumulative=1, pilot=1, days30=30, days90=90))
        self.assertEqual(report['selected_blocks'], 0)
        for r in report['sensitivity']:
            self.assertEqual(r['incremental_vs_hold_nok'], 0)
            self.assertGreater(r['final_nok'], r['initial_nok'])
        text = markdown(report)
        self.assertIn('ANTATT', text)
        self.assertIn('MÅLTE Swap-events', text)
        self.assertIn('ikke faktisk fakturert CU', text)

    def test_no_complete_report_from_truncated_or_duplicate_checkpoints(self):
        manifest, rows, _ = self.inputs()
        with tempfile.TemporaryDirectory() as d:
            folder = pathlib.Path(d)
            for bad in ([rows[0]], [rows[0], rows[0]]):
                (folder / 'blocks.jsonl').write_text('\n'.join(json.dumps(r) for r in bad), encoding='utf-8')
                with self.assertRaises(ValueError):
                    load_rows(folder, manifest)
            (folder / 'blocks.jsonl').write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
            self.assertEqual(len(load_rows(folder, manifest)), 2)
            manifest['complete'] = False
            with self.assertRaises(ValueError):
                load_rows(folder, manifest)


if __name__ == '__main__':
    unittest.main()
