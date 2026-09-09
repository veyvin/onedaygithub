"""核心逻辑单元测试。

运行方式：
    pip install pytest
    pytest tests/ -v
"""
import os
from datetime import datetime

import pytest

import github_daily
from generate_post import (
    extract_title_and_content,
    format_code_blocks,
    _derive_tags_from_repo,
)
from publish_to_halo import (
    _to_ascii_slug,
    generate_unique_slug,
    get_beijing_time,
)


# ----------------------------- generate_post.py -----------------------------

def test_format_code_blocks_converts_fenced_code_with_language():
    src = "前\n```python\nprint('hi')\n```\n后"
    out = format_code_blocks(src)
    assert '<pre><code class="language-python">' in out
    assert "print('hi')" in out
    assert "```" not in out


def test_format_code_blocks_handles_fenced_code_without_language():
    src = "```\nplain code\n```"
    out = format_code_blocks(src)
    assert '<pre><code class="language-">' in out
    assert "plain code" in out


def test_format_code_blocks_converts_inline_code():
    src = "使用 `console.log()` 调试"
    out = format_code_blocks(src)
    assert "<code>console.log()</code>" in out


def test_format_code_blocks_preserves_plain_text():
    src = "纯文本没有代码块"
    assert format_code_blocks(src) == src


def test_extract_title_and_content_from_full_html_doc():
    html = (
        "<!DOCTYPE html><html><head><title>页面标题</title></head>"
        "<body><h1>主标题</h1><p>正文</p></body></html>"
    )
    title, content = extract_title_and_content(html)
    assert title == "主标题"  # 优先 h1
    assert "<p>正文</p>" in content


def test_extract_title_and_content_falls_back_to_title_tag():
    html = "<html><head><title>只有标题</title></head><body></body></html>"
    title, _ = extract_title_and_content(html)
    assert title == "只有标题"


def test_extract_title_and_content_from_plain_text():
    # 标题需 > 5 个字符才会被采纳（见 extract_title_and_content 中的过滤逻辑）
    # 标题被识别后，正文从第二行开始（去掉标题行），首部空行会被 strip
    text = "这是一个比较长的标题\n\n<p>这是正文</p>"
    title, content = extract_title_and_content(text)
    assert title == "这是一个比较长的标题"
    assert content == "<p>这是正文</p>"


def test_extract_title_and_content_empty_input():
    title, content = extract_title_and_content("")
    assert title == ""
    assert content == ""


def test_derive_tags_from_repo_matches_keywords():
    # 关键词按 keywords 列表顺序匹配，最多返回 3 个
    repo = {"name": "python-trading-bot", "desc": "A CLI for quant trading"}
    tags = _derive_tags_from_repo(repo)
    # python（来自 name）、quant、trading（来自 desc）是按顺序命中的前 3 个
    assert "Python" in tags
    assert "Trading" in tags
    assert "Quant" in tags
    assert len(tags) == 3  # 上限为 3


def test_derive_tags_from_repo_detects_cli():
    # 单独验证 CLI 关键词能被识别
    repo = {"name": "my-tool", "desc": "a useful cli"}
    tags = _derive_tags_from_repo(repo)
    assert "Cli" in tags


def test_derive_tags_from_repo_no_match_returns_empty():
    repo = {"name": "random-project", "desc": "a thing"}
    assert _derive_tags_from_repo(repo) == []


def test_derive_tags_from_repo_caps_at_three():
    # 关键词覆盖很多，但只应返回最多 3 个
    repo = {"name": "python rust javascript go java", "desc": "ai llm cli web quant"}
    tags = _derive_tags_from_repo(repo)
    assert len(tags) <= 3


def test_derive_tags_from_repo_handles_missing_fields():
    assert _derive_tags_from_repo({}) == []
    assert _derive_tags_from_repo({"name": None, "desc": None}) == []


# ----------------------------- publish_to_halo.py -----------------------------

def test_to_ascii_slug_basic():
    assert _to_ascii_slug("hello world") == "hello-world"


def test_to_ascii_slug_preserves_chinese():
    s = _to_ascii_slug("开源项目")
    # 中文字符应被保留；若首字符非 ASCII 则补 cat- 前缀
    assert "开源项目" in s or s.startswith("cat-")


def test_to_ascii_slug_empty_falls_back_to_cat_default():
    # 空字符串：首字符非 ASCII 检查触发 cat- 前缀
    assert _to_ascii_slug("") == "cat-default"


def test_to_ascii_slug_max_length_63():
    s = _to_ascii_slug("a" * 100)
    assert len(s) <= 63


def test_generate_unique_slug_format():
    slug, date = generate_unique_slug("owner/repo", "2026-09-08")
    assert slug.startswith("github-trending-2026-09-08-")
    assert "owner-repo" in slug
    assert date == "2026-09-08"


def test_generate_unique_slug_truncates_long_names():
    long_name = "a" * 100
    slug, _ = generate_unique_slug(long_name, "2026-09-08")
    assert len(slug) <= 60


def test_generate_unique_slug_strips_special_chars():
    slug, _ = generate_unique_slug("foo.bar_BAZ!", "2026-09-08")
    # 只保留 a-z0-9-_
    suffix = slug.rsplit("-", 1)[-1]
    for ch in suffix:
        assert ch in "abcdefghijklmnopqrstuvwxyz0123456789-_"


def test_get_beijing_time_adds_eight_hours():
    """GitHub 的 UTC 日期字符串加 8 小时得到北京时间的早 8 点。"""
    result = get_beijing_time("2026-09-08")
    assert result.year == 2026
    assert result.month == 9
    assert result.day == 8
    assert result.hour == 8


# ----------------------------- github_daily.py -----------------------------

@pytest.fixture
def isolated_csv(tmp_path, monkeypatch):
    """把 CSV_FILE 指向临时目录，隔离测试。"""
    csv_path = tmp_path / "processed_repos.csv"
    monkeypatch.setattr(github_daily, "CSV_FILE", str(csv_path))
    return csv_path


def test_load_processed_repos_nonexistent_file(isolated_csv):
    assert github_daily.load_processed_repos() == set()


def test_load_processed_repos_empty_file(isolated_csv):
    isolated_csv.write_text("")
    assert github_daily.load_processed_repos() == set()


def test_load_processed_repos_only_header(isolated_csv):
    isolated_csv.write_text("name,url,processed_date\n")
    assert github_daily.load_processed_repos() == set()


def test_load_processed_repos_with_data(isolated_csv):
    isolated_csv.write_text(
        "name,url,processed_date\n"
        "foo/bar,https://github.com/foo/bar,2026-01-01\n"
        "baz/qux,https://github.com/baz/qux,2026-01-02\n"
    )
    result = github_daily.load_processed_repos()
    assert "https://github.com/foo/bar" in result
    assert "https://github.com/baz/qux" in result
    assert len(result) == 2


def test_save_processed_repo_creates_new_file(isolated_csv):
    repo = {"name": "foo/bar", "url": "https://github.com/foo/bar", "date": "2026-01-01"}
    assert github_daily.save_processed_repo(repo) is True
    content = isolated_csv.read_text()
    assert "name,url,processed_date" in content
    assert "https://github.com/foo/bar" in content


def test_save_processed_repo_appends_to_existing(isolated_csv):
    isolated_csv.write_text("name,url,processed_date\n")
    repo = {"name": "foo/bar", "url": "https://github.com/foo/bar", "date": "2026-01-01"}
    assert github_daily.save_processed_repo(repo) is True
    lines = isolated_csv.read_text().splitlines()
    assert len(lines) == 2  # 表头 + 1 行数据
    assert "https://github.com/foo/bar" in lines[1]


def test_save_processed_repo_returns_false_on_write_error(tmp_path, monkeypatch):
    # 把 CSV 指向一个不存在的目录，触发写入异常
    monkeypatch.setattr(github_daily, "CSV_FILE", str(tmp_path / "nope" / "x.csv"))
    repo = {"name": "foo/bar", "url": "https://github.com/foo/bar", "date": "2026-01-01"}
    assert github_daily.save_processed_repo(repo) is False
