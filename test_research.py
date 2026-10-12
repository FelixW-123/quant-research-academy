"""Run: python3 -m unittest test_research.py"""
import copy
import math
from pathlib import Path
import unittest
import research as q


class ResearchChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prices = q.load_prices(Path(__file__).with_name('sample_prices.csv'))
        cls.samples = q.build_samples(cls.prices)
        cls.parts = q.split_samples(cls.samples)

    def test_feature_clock(self):
        prices = copy.deepcopy(self.prices)
        for row in prices[200:]:
            for k in ['open', 'high', 'low', 'close']:
                row[k] *= 1.7
        changed = q.build_samples(prices)
        self.assertEqual([r['x'] for r in changed[:190]], [r['x'] for r in self.samples[:190]])
        self.assertEqual(len(self.samples), 709)
        self.assertEqual(self.samples[0]['y'], int(self.prices[11]['close'] > self.prices[11]['open']))

    def test_time_split(self):
        self.assertEqual([len(x) for x in self.parts.values()], [425, 141, 141])
        self.assertLess(self.parts['train'][-1]['label_date'], self.parts['validation'][0]['date'])
        self.assertLess(self.parts['validation'][-1]['label_date'], self.parts['test'][0]['date'])

    def test_position(self):
        p = q.size_position()
        self.assertEqual(p['shares'], 238)
        self.assertLessEqual(p['planned_loss'], 500)
        self.assertLessEqual(p['cash_used'], 80000)
        self.assertEqual(q.size_position(lot=100)['shares'], 200)
        self.assertEqual(q.size_position(existing_risk_pct=2)['shares'], 0)
        with self.assertRaises(ValueError):
            q.size_position(stop=50)
        with self.assertRaises(ValueError):
            q.size_position(entry=math.nan)

    def test_cost_accounting(self):
        result = q.simulate([{'open': 100, 'close': 100, 'label_date': '2022-01-04'}], [1],
                            cap_pct=10, fee_bps=10, slip_bps=0)
        self.assertGreater(result['costs'], 0)
        self.assertAlmostEqual(result['equity'], 100000 - result['costs'])

    def test_metrics(self):
        self.assertAlmostEqual(q.metrics([{'y': 1}, {'y': 0}], [.8, .6])['brier'], .2)
        self.assertAlmostEqual(q.max_drawdown([100, 120, 90, 110]), .25)

    def test_train_preprocessing(self):
        model = q.fit_logistic(self.parts['train'])
        for j, value in enumerate(model['means']):
            self.assertAlmostEqual(value, q.mean(r['x'][j] for r in self.parts['train']))
        before = copy.deepcopy(model)
        q.predict(model, self.parts['test'])
        self.assertEqual(model, before)


if __name__ == '__main__':
    unittest.main()
