import unittest

from rag.cleaner import clean_text


class CleanerTests(unittest.TestCase):
    def test_remove_blank_and_page_noise(self):
        raw = "第 1 页\n\n  锂电池 运输声明 \n\nPage 2\n内容"
        self.assertEqual(clean_text(raw), "锂电池 运输声明\n内容")


if __name__ == "__main__":
    unittest.main()
