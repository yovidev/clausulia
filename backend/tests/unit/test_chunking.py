import pytest

from app.ingestion.chunking import PageText, chunk_pages, normalize_text

SIZE = 200
OVERLAP = 40


def _sentences(n: int, prefix: str = "Cláusula") -> str:
    return " ".join(f"{prefix} {i} establece una obligación del proveedor." for i in range(n))


def test_empty_pages_produce_no_chunks() -> None:
    assert chunk_pages([PageText(1, ""), PageText(2, "   \n\n ")], SIZE, OVERLAP) == []


def test_short_page_is_a_single_chunk_with_its_page() -> None:
    chunks = chunk_pages([PageText(3, "El contrato se renueva cada año.")], SIZE, OVERLAP)
    assert len(chunks) == 1
    assert chunks[0].page_number == 3
    assert chunks[0].chunk_index == 0
    assert chunks[0].content == "El contrato se renueva cada año."


def test_no_chunk_exceeds_max_size() -> None:
    chunks = chunk_pages([PageText(1, _sentences(60))], SIZE, OVERLAP)
    assert len(chunks) > 1
    assert all(len(c.content) <= SIZE for c in chunks)


def test_chunks_never_cross_pages() -> None:
    pages = [PageText(1, _sentences(20, "Alfa")), PageText(2, _sentences(20, "Beta"))]
    chunks = chunk_pages(pages, SIZE, OVERLAP)
    for chunk in chunks:
        if chunk.page_number == 1:
            assert "Beta" not in chunk.content
        else:
            assert "Alfa" not in chunk.content
    assert {c.page_number for c in chunks} == {1, 2}


def test_indexes_are_consecutive_across_pages() -> None:
    pages = [PageText(1, _sentences(15)), PageText(2, _sentences(15))]
    chunks = chunk_pages(pages, SIZE, OVERLAP)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_consecutive_chunks_overlap() -> None:
    chunks = chunk_pages([PageText(1, _sentences(30))], SIZE, OVERLAP)
    first = " ".join(chunks[0].content.split())
    start_of_second = " ".join(chunks[1].content.split()[:3])
    assert start_of_second in first


def test_zero_overlap_does_not_repeat_text() -> None:
    chunks = chunk_pages([PageText(1, _sentences(30))], SIZE, 0)
    words = [w for c in chunks for w in c.content.split()]
    assert words == _sentences(30).split()


def test_long_text_without_punctuation_is_split_by_words() -> None:
    text = "palabra " * 120
    chunks = chunk_pages([PageText(1, text)], SIZE, OVERLAP)
    assert all(len(c.content) <= SIZE for c in chunks)
    assert all("palabra" in c.content for c in chunks)


def test_giant_word_is_split_by_characters() -> None:
    chunks = chunk_pages([PageText(1, "x" * 450)], SIZE, 0)
    assert [len(c.content) for c in chunks] == [200, 200, 50]


@pytest.mark.parametrize(("size", "overlap"), [(0, 0), (100, 100), (100, -1)])
def test_invalid_parameters_raise(size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        chunk_pages([PageText(1, "texto")], size, overlap)


def test_normalize_joins_hyphenated_words_and_collapses_whitespace() -> None:
    raw = "La renova-\nción   automática\r\n\n\n\nse aplica."
    assert normalize_text(raw) == "La renovación automática\n\nse aplica."
