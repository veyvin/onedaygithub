"""核心逻辑单元测试。

运行方式：
    pip install pytest
    pytest tests/ -v
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

import github_daily
from generate_post import (
    extract_title_and_content,
    format_code_blocks,
    strip_emoji,
    strip_leading_title,
    _derive_tags_from_repo,
)
import publish_to_halo
from publish_to_halo import (
    _is_cloudflare_challenge,
    _to_ascii_slug,
    build_headers,
    generate_unique_slug,
    get_beijing_time,
    halo_request,
    now_beijing,
    publish_to_halo as publish_post,
    CloudflareChallengeError,
    HaloAuthError,
)


# ----------------------------- generate_post.py -----------------------------

# ---------------- 公众号标题：去除 emoji ----------------

def test_strip_emoji_removes_leading_and_trailing_emoji():
    assert strip_emoji("🚀 LinkSwift：八大网盘直链工具") == "LinkSwift：八大网盘直链工具"
    assert strip_emoji("Ghidra 框架探索之旅 🛠️🔍") == "Ghidra 框架探索之旅"


def test_strip_emoji_keeps_chinese_punctuation_and_ascii():
    t = "android/skills：当官方仓库聊「技能」时 🤖"
    assert strip_emoji(t) == "android/skills：当官方仓库聊「技能」时"
    # 纯 ASCII 标题原样返回
    assert strip_emoji("Hello-World/repo: plain title") == "Hello-World/repo: plain title"


def test_strip_emoji_handles_flag_and_zwj_sequences():
    # 国旗由两个区域指示符组成，VS16/ZWJ 组合也要整体去掉
    assert strip_emoji("🇨🇳 技巧 ✍️") == "技巧"
    assert strip_emoji("🛠️ 工具") == "工具"


def test_strip_emoji_handles_empty_input():
    assert strip_emoji("") == ""
    assert strip_emoji(None) == ""


def test_strip_emoji_does_not_strip_normal_dash():
    assert strip_emoji("Rust — 3 分钟上手") == "Rust — 3 分钟上手"


# ---------------- 正文：只去掉重复标题，不插入任何卡片 ----------------

def test_strip_leading_title_removes_duplicate_title_line():
    out = strip_leading_title("🚀 标题：正文\n<p>第一段</p>", "🚀 标题：正文")
    assert out == "<p>第一段</p>"


def test_strip_leading_title_handles_h1_and_blank_lines():
    out = strip_leading_title("\n\n<h1>标题</h1>\n<p>正文</p>", "标题")
    assert out == "<p>正文</p>"


def test_strip_leading_title_keeps_body_when_no_duplicate():
    content = "<p>正文第一段</p>\n<p>正文第二段</p>"
    assert strip_leading_title(content, "标题") == content


def test_strip_leading_title_handles_empty_content():
    assert strip_leading_title("", "标题") == ""


def test_content_is_not_modified_with_extra_blocks():
    """正文只做去重标题，不得被插入项目信息卡片等额外内容。"""
    out = strip_leading_title("🚀 标题\n<p>正文</p>", "🚀 标题")
    assert "<div" not in out
    assert "<table" not in out
    assert out == "<p>正文</p>"

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


# ------------------ publish_to_halo.py: 请求层（Cloudflare 防护） ------------------

def _fake_response(status_code=200, headers=None, text="", json_body=None):
    """构造一个只带必要属性的假响应对象。"""
    return type(
        "FakeResponse",
        (),
        {
            "status_code": status_code,
            "headers": headers or {},
            "text": text,
            "json": lambda self: (json_body if json_body is not None else {}),
        },
    )()


def test_build_headers_includes_browser_user_agent(monkeypatch):
    """Cloudflare 会拦截 python-requests 默认 UA，请求头必须伪装成浏览器。"""
    monkeypatch.delenv("HALO_USER_AGENT", raising=False)
    headers = build_headers("pat-test")
    assert "Mozilla/5.0" in headers["User-Agent"]
    assert "python-requests" not in headers["User-Agent"]
    assert headers["Authorization"] == "Bearer pat-test"
    assert headers["Content-Type"] == "application/json"


def test_build_headers_user_agent_can_be_overridden(monkeypatch):
    monkeypatch.setenv("HALO_USER_AGENT", "MyBot/1.0")
    assert build_headers("pat-test")["User-Agent"] == "MyBot/1.0"


def test_is_cloudflare_challenge_detects_cf_mitigated_header():
    resp = _fake_response(403, {"cf-mitigated": "challenge"}, "")
    assert _is_cloudflare_challenge(resp) is True


def test_is_cloudflare_challenge_detects_just_a_moment_body():
    resp = _fake_response(403, {"content-type": "text/html; charset=UTF-8"},
                          "<html><head><title>Just a moment...</title>")
    assert _is_cloudflare_challenge(resp) is True


def test_is_cloudflare_challenge_ignores_normal_responses():
    assert _is_cloudflare_challenge(_fake_response(200, {}, "{}")) is False
    # Halo 自身的 401/403 不算 Cloudflare 挑战
    assert _is_cloudflare_challenge(_fake_response(401, {}, "")) is False


def test_halo_request_raises_on_cloudflare_challenge(monkeypatch):
    monkeypatch.setattr(
        publish_to_halo.requests, "request",
        lambda *a, **kw: _fake_response(403, {"cf-mitigated": "challenge"}, ""),
    )
    with pytest.raises(CloudflareChallengeError):
        halo_request("GET", "https://example.com/apis/x", build_headers("pat-x"))


def test_halo_request_raises_on_login_redirect(monkeypatch):
    """未认证时 Halo 会 302 到 /login；不能被当成 200 成功页。"""
    monkeypatch.setattr(
        publish_to_halo.requests, "request",
        lambda *a, **kw: _fake_response(302, {"location": "/login?authentication_required"}, ""),
    )
    with pytest.raises(HaloAuthError):
        halo_request("GET", "https://example.com/apis/x", build_headers("pat-x"))


def test_halo_request_raises_on_halo_401(monkeypatch):
    monkeypatch.setattr(
        publish_to_halo.requests, "request",
        lambda *a, **kw: _fake_response(401, {}, ""),
    )
    with pytest.raises(HaloAuthError):
        halo_request("GET", "https://example.com/apis/x", build_headers("pat-x"))


def test_halo_request_disables_redirects(monkeypatch):
    """必须关闭自动重定向，否则登录页 HTML 会被误判成发布成功。"""
    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update(kwargs)
        return _fake_response(200, {}, "{}")

    monkeypatch.setattr(publish_to_halo.requests, "request", fake_request)
    halo_request("POST", "https://example.com/apis/x", build_headers("pat-x"), json={})
    assert captured["allow_redirects"] is False


def test_halo_request_returns_ok_response(monkeypatch):
    monkeypatch.setattr(
        publish_to_halo.requests, "request",
        lambda *a, **kw: _fake_response(200, {}, '{"items": []}'),
    )
    resp = halo_request("GET", "https://example.com/apis/x", build_headers("pat-x"))
    assert resp.status_code == 200


# ------------------ publish_to_halo.py: 发布时间（真实东八区时间） ------------------

def test_now_beijing_uses_utc_plus_8_offset():
    dt = now_beijing()
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timedelta(hours=8)


def test_now_beijing_reflects_current_instant_not_local_wall_clock():
    """GitHub Actions 跑在 UTC，若读本地墙钟时间，发布时间会整体偏 8 小时。

    换算回 UTC 后应与「当前真实时刻」一致，说明是时刻换算而非墙钟时间。
    """
    dt = now_beijing()
    drift = dt.astimezone(timezone.utc) - datetime.now(timezone.utc)
    assert abs(drift.total_seconds()) < 5


def test_publish_payload_uses_real_beijing_publish_time(monkeypatch):
    """publishTime 必须是真实的当前北京时间，而不是固定 08:00。"""
    captured = {}

    def fake_halo_request(method, url, headers, **kwargs):
        captured.update(kwargs)
        return _fake_response(200, {}, json_body={"metadata": {"name": "post-1"}})

    monkeypatch.setattr(publish_to_halo, "halo_request", fake_halo_request)
    monkeypatch.setattr(
        publish_to_halo, "resolve_categories_and_tags",
        lambda *args, **kwargs: (["cat-id"], ["tag-id"]),
    )
    monkeypatch.setenv("HALO_TOKEN", "pat-x")

    post_data = {
        "repo_info": {"name": "owner/repo", "date": "2026-10-17"},
        "title": "标题",
        "content": "<p>正文</p>",
    }
    assert publish_post(post_data) is not None

    publish_time = captured["json"]["post"]["spec"]["publishTime"]
    # Halo 期望的 ISO-8601 带时区格式
    dt = datetime.strptime(publish_time, "%Y-%m-%dT%H:%M:%S%z")
    assert dt.utcoffset() == timedelta(hours=8)
    drift = dt.astimezone(timezone.utc) - datetime.now(timezone.utc)
    assert abs(drift.total_seconds()) < 60
    assert not publish_time.endswith("T08:00:00+08:00")


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
