import json
import tempfile
import unittest
from unittest.mock import patch
from decimal import Decimal
from pathlib import Path

import fundflow_adapter as adapter


class FundflowAdapterTests(unittest.TestCase):
    def _item(self, code="600000", name="浦发银行", main_net="123456.78"):
        item = [None] * 20
        item[0] = code
        item[1] = name
        item[5] = "12.345"
        item[6] = "1.23"
        item[7] = "987654321.10"
        item[11] = "200000"
        item[12] = "76543.22"
        item[13] = main_net
        item[19] = "2.50"
        return item

    def test_normalizes_kaipanla_stock_fields_to_fundflow_contract(self):
        row = adapter.normalize_stock_row(self._item())
        self.assertEqual(row["stock_code"], "600000")
        self.assertEqual(row["stock_name"], "浦发银行")
        self.assertEqual(row["market"], "SH")
        self.assertEqual(row["latest_price"], Decimal("12.345"))
        self.assertEqual(row["turnover_amount"], Decimal("987654321.10"))
        self.assertEqual(row["main_net_inflow"], Decimal("123456.78"))
        self.assertEqual(row["main_net_inflow_ratio"], Decimal("2.50"))
        self.assertIsNone(row["volume"])
        self.assertIsNone(row["super_large_net_inflow"])

    def test_rejects_non_a_shares_and_rows_without_main_net_inflow(self):
        self.assertIsNone(adapter.normalize_stock_row(self._item(code="200001")))
        self.assertIsNone(adapter.normalize_stock_row(self._item(main_net="--")))

    def test_deduplicates_by_stock_code_and_supports_types(self):
        rows = adapter.normalize_rows([self._item(), self._item(), self._item(code="300001")])
        self.assertEqual([row["stock_code"] for row in rows], ["300001", "600000"])
        self.assertEqual(adapter.parse_types("6"), [6])
        self.assertEqual(adapter.parse_types("0, 6, 19"), [0, 6, 19])
        self.assertEqual(adapter.parse_types("all"), list(range(20)))

    def test_writes_jsonl_with_decimal_as_string(self):
        row = adapter.normalize_stock_row(self._item())
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "flow.jsonl"
            self.assertEqual(adapter.write_jsonl([row], output), 1)
            saved = json.loads(output.read_text())
        self.assertEqual(saved["main_net_inflow"], "123456.78")
        self.assertEqual(tuple(saved), adapter.FUND_FLOW_FIELDS)

    def test_discovery_stops_after_requested_number_of_sub_plates(self):
        responses = iter([
            {"errcode": "0", "list": [["801001"], ["801002"]]},
            {"errcode": "0", "List": [["801101"], ["801102"]]},
        ])
        with patch.object(adapter.crawler, "do_request", side_effect=lambda *_args, **_kwargs: next(responses)):
            self.assertEqual(adapter.discover_sub_plate_ids("2026-08-25", max_plates=1), ["801101"])

    def test_discovery_treats_upstream_error_as_failure(self):
        with patch.object(adapter.crawler, "do_request", return_value={"errcode": 1020, "errmsg": "参数出错"}):
            with self.assertRaises(adapter.KplApiError):
                adapter.discover_sub_plate_ids("2026-08-26", max_plates=1)

    def test_requires_an_explicit_historical_date(self):
        self.assertEqual(adapter.main(["--input-csv", "does-not-matter.csv"]), 2)


if __name__ == "__main__":
    unittest.main()
