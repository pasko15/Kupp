import sqlite3
import unittest

from fastapi.testclient import TestClient

from backend.kupp.api.database import connect_readonly
from backend.kupp.api.main import app
from backend.kupp.config import DB_PATH


class ReadOnlyApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_docs_and_openapi_are_available(self):
        docs = self.client.get('/docs')
        self.assertEqual(docs.status_code, 200)
        self.assertIn('Swagger UI', docs.text)
        schema = self.client.get('/openapi.json')
        self.assertEqual(schema.status_code, 200)
        self.assertIn('/items/{item_id}/history', schema.json()['paths'])

    def test_basket_has_match_status_and_current_price_fields(self):
        response = self.client.get('/basket')
        self.assertEqual(response.status_code, 200)
        milk = next(item for item in response.json()['items'] if item['item_id'] == 'milk')
        self.assertEqual(milk['match_status'], 'matched')
        self.assertIn('cheapest_fresh_store', milk)
        self.assertIn('unit_price', milk)

    def test_item_history_reports_insufficient_data(self):
        response = self.client.get('/items/rice/history')
        self.assertEqual(response.status_code, 200)
        rice = response.json()
        self.assertEqual(rice['item_id'], 'rice')
        self.assertEqual(len(rice['stores']), 1)
        self.assertEqual(rice['stores'][0]['regular_price_status'], 'insufficient data')
        self.assertEqual(len(rice['stores'][0]['observations']), 41)

    def test_missing_item_returns_404(self):
        self.assertEqual(self.client.get('/items/no-such-item/history').status_code, 404)

    def test_readonly_database_uri_rejects_writes(self):
        before = sqlite3.connect(DB_PATH).execute('SELECT COUNT(*) FROM price_observations').fetchone()[0]
        with connect_readonly() as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("UPDATE products SET product_name='changed' WHERE item_id='milk'")
        after = sqlite3.connect(DB_PATH).execute('SELECT COUNT(*) FROM price_observations').fetchone()[0]
        self.assertEqual(before, after)

    def test_deals_and_health_use_response_models(self):
        deals = self.client.get('/deals')
        self.assertEqual(deals.status_code, 200)
        for deal in deals.json()['deals']:
            self.assertEqual(deal['label'], 'price drop vs history')
        health = self.client.get('/health')
        self.assertEqual(health.status_code, 200)
        self.assertIsNotNone(health.json()['last_import'])
        self.assertGreater(health.json()['days_of_history'], 0)
        self.assertIn('stale_count', health.json())
        self.assertIn('unmatched_items', health.json())


if __name__ == '__main__':
    unittest.main()
