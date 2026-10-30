"""Testes locais, sem rede e sem dependências externas, do inventário CKAN."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inventariar_ckan.py"
spec = importlib.util.spec_from_file_location("inventariar_ckan", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class InventoryTests(unittest.TestCase):
    def test_reject_unknown_action(self):
        with self.assertRaises(ValueError):
            module.get_ckan_json("unknown", {})

    def test_paginated_search(self):
        response1 = {"count": 3, "results": [{"id": "a"}, {"id": "b"}]}
        response2 = {"count": 3, "results": [{"id": "c"}]}
        with patch.object(module, "get_ckan_json", side_effect=[response1, response2]) as mock:
            items = module.discover("resultados 2026", rows=2)
        self.assertEqual(len(items), 3)
        self.assertEqual(mock.call_count, 2)

    def test_resource_minimization(self):
        result = module.simplified_resource({"id": "x", "name": "dados.csv", "url": "https://example.test/r",
                                                 "secret_unrequested": "value"})
        self.assertEqual(result["id"], "x")
        self.assertNotIn("secret_unrequested", result)

    def test_no_large_download_in_exposed_flow(self):
        self.assertFalse(hasattr(module, "download_election_results"))


if __name__ == "__main__":
    unittest.main()
