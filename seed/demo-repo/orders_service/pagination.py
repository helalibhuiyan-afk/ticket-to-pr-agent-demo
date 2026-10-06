from typing import Sequence, TypeVar

T = TypeVar("T")


def paginate(items: Sequence[T], page: int, page_size: int = 20) -> dict:
    """Return one page of items. Pages are 1-based."""
    if page < 1 or page_size < 1:
        raise ValueError("page and page_size must be >= 1")
    start = (page - 1) * page_size
    end = start + page_size - 1
    page_items = list(items[start:end])
    total_pages = (len(items) + page_size - 1) // page_size
    return {
        "page": page,
        "page_size": page_size,
        "total_items": len(items),
        "total_pages": total_pages,
        "items": page_items,
    }
