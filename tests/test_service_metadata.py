import unittest

from wecom_kf.admin_metadata import admin_metadata
from wecom_kf.service_catalog import SERVICES, registered_services


class ServiceMetadataTests(unittest.TestCase):
    def test_metadata_matches_registered_services_and_filter_contract(self):
        data = admin_metadata()
        self.assertEqual([(x["code"], x["name"]) for x in data["services"]], list(SERVICES.items()))
        self.assertEqual({x["code"] for x in data["job_kinds"]}, {"verify", "list", "solve", "purchase", "payment_check"})
        self.assertIn("queued", {x["code"] for x in data["job_statuses"]})
        self.assertFalse(next(x for x in data["job_statuses"] if x["code"] == "queued")["filterable"])

    def test_result_is_safe_to_mutate(self):
        first = admin_metadata()
        first["services"].clear()
        self.assertEqual(
            registered_services(),
            [{"code": "educoder", "name": "头歌"}, {"code": "shuori", "name": "朔日"}],
        )
        self.assertTrue(admin_metadata()["services"])


if __name__ == "__main__":
    unittest.main()
