import unittest

from orders_service.pagination import paginate


class PaginationTests(unittest.TestCase):
    def test_metadata(self):
        result = paginate(list(range(45)), page=1, page_size=20)
        self.assertEqual(result["total_items"], 45)
        self.assertEqual(result["total_pages"], 3)

    def test_page_past_end_is_empty(self):
        self.assertEqual(paginate(list(range(5)), page=3, page_size=5)["items"], [])

    def test_invalid_page(self):
        with self.assertRaises(ValueError):
            paginate([1, 2, 3], page=0)
