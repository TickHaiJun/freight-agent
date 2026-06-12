import unittest

from rag.query_analyzer import analyze_query


class QueryAnalyzerTests(unittest.TestCase):
    def test_dangerous_goods_rule(self):
        result = analyze_query("锂电池货物需要什么声明文件")
        self.assertEqual(result["filters"], {"category": "dangerous_goods"})

    def test_operations_rule(self):
        result = analyze_query("ACCOS 系统怎么录入分单件数")
        self.assertEqual(result["filters"], {"category": "operations"})

    def test_general_cargo_rule(self):
        result = analyze_query("普货不带电授权委托书怎么填写")
        self.assertEqual(result["filters"], {"category": "general_cargo"})

    def test_customs_rule(self):
        result = analyze_query("上海口岸空运出口报关品名清单是做什么用的")
        self.assertEqual(result["filters"], {"category": "customs"})


if __name__ == "__main__":
    unittest.main()
