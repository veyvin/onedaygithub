"""repo_context.py 的单元测试：README 清洗、章节挑选、上下文抓取。"""
import repo_context
from repo_context import (
    clean_readme,
    fetch_repo_context,
    parse_owner_repo,
    select_readme_sections,
    split_sections,
)


def test_parse_owner_repo_valid():
    assert parse_owner_repo("owner/repo") == ("owner", "repo")
    assert parse_owner_repo(" /owner/repo/ ") == ("owner", "repo")


def test_parse_owner_repo_invalid():
    assert parse_owner_repo(None) is None
    assert parse_owner_repo("") is None
    assert parse_owner_repo("owner") is None
    assert parse_owner_repo("a/b/c") is None


def test_clean_readme_removes_badges_images_and_html():
    raw = """# Project
[![Build](https://img.shields.io/badge/build-passing-green)](https://ci)
![logo](https://example.com/logo.png)
<p align="center"><img src="x.png"></p>
Real description with <b>bold</b> text.
"""
    cleaned = clean_readme(raw)
    assert "shields.io" not in cleaned
    assert "logo.png" not in cleaned
    assert "Real description with bold text." in cleaned
    assert "# Project" in cleaned


def test_clean_readme_keeps_code_fences():
    raw = "text\n```html\n<div>keep</div>\n```\n"
    cleaned = clean_readme(raw)
    assert "<div>keep</div>" in cleaned


def test_split_sections_ignores_headings_inside_code_fence():
    text = "# Title\nintro\n```bash\n# not a heading\necho hi\n```\n## Usage\nrun it"
    sections = split_sections(text)
    headings = [heading for heading, _ in sections]
    assert headings == ["Title", "Usage"]
    assert "not a heading" in sections[0][1]


def test_select_readme_sections_prioritizes_features_and_usage():
    text = """# Demo
Intro paragraph.

## License
MIT.

## Usage
Run `demo`.

## Features
- fast
- small

## Architecture
layers
"""
    excerpt = select_readme_sections(text, max_chars=400)
    assert "## Usage" in excerpt
    assert "## Features" in excerpt
    assert excerpt.index("## Features") < excerpt.index("## Architecture")


def test_select_readme_sections_respects_max_chars():
    text = "# X\n" + "a" * 1000 + "\n## Features\n" + "b" * 1000
    excerpt = select_readme_sections(text, max_chars=200)
    assert len(excerpt) <= 200


def test_fetch_repo_context_returns_empty_for_invalid_name(monkeypatch):
    called = []
    monkeypatch.setattr(
        repo_context, "fetch_repo_metadata",
        lambda name: called.append(name) or {},
    )
    monkeypatch.setattr(
        repo_context, "fetch_readme",
        lambda name: called.append(name) or "",
    )
    assert fetch_repo_context("invalid") == {}
    assert called == []


def test_fetch_repo_context_combines_metadata_and_readme(monkeypatch):
    monkeypatch.setattr(
        repo_context, "fetch_repo_metadata",
        lambda name: {"topics": ["ai"], "language": "Go"},
    )
    monkeypatch.setattr(
        repo_context, "fetch_readme",
        lambda name: "# Demo\n\n## Features\n- fast",
    )
    context = fetch_repo_context("owner/demo", max_chars=500)
    assert context["metadata"]["language"] == "Go"
    assert "## Features" in context["readme_excerpt"]
