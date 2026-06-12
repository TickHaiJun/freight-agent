import unittest

from graph.origin_parser import ALL_ORIGIN_CODES_TEXT, extract_origin_codes, normalize_origin_codes


class OriginParserTests(unittest.TestCase):
    def test_extract_origin_codes_for_multi_city_message(self):
        self.assertEqual(
            extract_origin_codes("从上海、香港、南京飞洛杉矶多少钱"),
            "pvg,hkg,nkg",
        )

    def test_extract_origin_codes_for_all_origin_query(self):
        self.assertEqual(
            extract_origin_codes("全部港口查一下飞洛杉矶"),
            ALL_ORIGIN_CODES_TEXT,
        )

    def test_extract_origin_codes_handles_fawang_without_leaking_destination(self):
        self.assertEqual(
            extract_origin_codes("从南京，上海，发往洛杉矶今天多少钱"),
            "nkg,pvg",
        )

    def test_normalize_origin_codes_deduplicates_and_lowercases(self):
        self.assertEqual(normalize_origin_codes("PVG, hkg,PVG,NKG"), "pvg,hkg,nkg")


if __name__ == "__main__":
    unittest.main()
