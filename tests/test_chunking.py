from hr_assistant.rag.chunking import MAX_CHUNK_CHARS, chunk_markdown_file

DOC = """---
title: Test Policy
description: something
---

Intro paragraph before any section.

## Vacations

You can take vacations. {{% note %}}shortcode gone{{% /note %}}

### Approval

Ask your manager first.

## Expenses

Submit receipts within 30 days.
"""


def test_chunks_carry_title_and_sections(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text(DOC, encoding="utf-8")
    chunks = chunk_markdown_file(path)

    assert chunks, "expected at least one chunk"
    assert all(c.title == "Test Policy" for c in chunks)
    assert all(c.source == "policy.md" for c in chunks)
    joined = "\n".join(c.text for c in chunks)
    assert "Ask your manager first." in joined
    assert "{{%" not in joined  # Hugo shortcode tags stripped...
    assert "shortcode gone" in joined  # ...but the wrapped content survives
    assert any("Vacations" in c.section for c in chunks)


def test_oversized_sections_are_split(tmp_path):
    big = "word " * 1500  # ~7500 chars in one section
    path = tmp_path / "big.md"
    path.write_text(f"# Big\n\n## Section\n\n{big}", encoding="utf-8")
    chunks = chunk_markdown_file(path)
    assert len(chunks) >= 2
    assert all(len(c.text) <= MAX_CHUNK_CHARS + 200 for c in chunks)


def test_title_falls_back_to_filename(tmp_path):
    path = tmp_path / "no-front-matter.md"
    path.write_text("Just a paragraph.", encoding="utf-8")
    chunks = chunk_markdown_file(path)
    assert chunks[0].title == "No Front Matter"


def test_real_corpus_chunks():
    """The committed handbook pages must produce a healthy corpus."""
    from hr_assistant.config import PROJECT_ROOT
    from hr_assistant.rag.chunking import chunk_directory

    chunks = chunk_directory(PROJECT_ROOT / "data" / "docs")
    assert len(chunks) > 50
    sources = {c.source for c in chunks}
    assert "time-off-types.md" in sources
    assert "ATTRIBUTION.md" not in sources  # excluded from the index
