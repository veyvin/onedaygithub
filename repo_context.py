"""抓取 GitHub 仓库元数据与 README，作为文章生成的事实来源。

设计目标：
- 只做只读抓取，失败不影响主流程（返回空结果，文章照常生成）；
- README 只保留高价值章节（Features / Install / Usage / Architecture 等），
  并限制总长度，避免把整篇 README 塞进提示词；
- 支持 GITHUB_TOKEN（Actions 自带），把 API 限额从 60/h 提到 5000/h。
"""
import os
import re

import requests

GITHUB_API = "https://api.github.com"
REQUEST_TIMEOUT = 15

# README 注入提示词的最大字符数（4000-6000 之间比较合适）
MAX_README_CHARS = int(os.getenv("README_MAX_CHARS", "6000"))

# 章节权重：数字越大越优先保留
SECTION_KEYWORDS = [
    ("features", 7),
    ("feature", 7),
    ("功能", 7),
    ("特性", 7),
    ("installation", 6),
    ("install", 6),
    ("getting started", 6),
    ("quick start", 6),
    ("quickstart", 6),
    ("安装", 6),
    ("快速开始", 6),
    ("usage", 5),
    ("how to use", 5),
    ("examples", 5),
    ("example", 5),
    ("使用", 5),
    ("示例", 5),
    ("architecture", 4),
    ("design", 4),
    ("how it works", 4),
    ("架构", 4),
    ("设计", 4),
    ("configuration", 3),
    ("config", 3),
    ("配置", 3),
]


def parse_owner_repo(full_name):
    """把 "owner/repo" 解析成 (owner, repo)；非法输入返回 None。"""
    if not isinstance(full_name, str):
        return None
    parts = full_name.strip().strip("/").split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def _github_headers(raw=False):
    headers = {
        "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "onedaygithub-bot",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_repo_metadata(full_name):
    """获取仓库元数据（默认分支、topics、语言等）；失败返回 {}。"""
    parsed = parse_owner_repo(full_name)
    if not parsed:
        return {}
    url = f"{GITHUB_API}/repos/{parsed[0]}/{parsed[1]}"
    try:
        response = requests.get(url, headers=_github_headers(), timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            print(f"  获取仓库元数据失败: {response.status_code}")
            return {}
        data = response.json()
    except (requests.exceptions.RequestException, ValueError) as exc:
        print(f"  获取仓库元数据出错: {exc}")
        return {}

    return {
        "default_branch": data.get("default_branch") or "main",
        "topics": data.get("topics") or [],
        "stars": data.get("stargazers_count"),
        "language": data.get("language") or "",
        "description": data.get("description") or "",
    }


def fetch_readme(full_name):
    """获取默认分支的 README 原文；失败返回空字符串。"""
    parsed = parse_owner_repo(full_name)
    if not parsed:
        return ""
    url = f"{GITHUB_API}/repos/{parsed[0]}/{parsed[1]}/readme"
    try:
        response = requests.get(url, headers=_github_headers(raw=True), timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            print(f"  获取 README 失败: {response.status_code}")
            return ""
        response.encoding = "utf-8"
        return response.text or ""
    except requests.exceptions.RequestException as exc:
        print(f"  获取 README 出错: {exc}")
        return ""


def clean_readme(text):
    """去掉徽章、图片、HTML 标签与多余空行；保留代码块原样。"""
    if not text:
        return ""

    cleaned_lines = []
    in_fence = False

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            cleaned_lines.append(line)
            continue

        # 代码块内部不改动，避免破坏示例代码
        if in_fence:
            cleaned_lines.append(line)
            continue

        # HTML 注释（单行）
        if stripped.startswith("<!--"):
            continue

        # 纯徽章/图片行：去掉后没有实际文字就整行丢弃
        if re.match(r"^\[?!\[", stripped) or stripped.startswith(("<img", "<p align")):
            without_media = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", stripped)
            without_media = re.sub(r"\[[^\]]*\]\([^)]*\)", "", without_media)
            if not without_media.strip("-|: "):
                continue

        # 行内图片与 HTML 标签
        line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
        line = re.sub(r"<[^>]+>", "", line)

        if line.strip() in ("</p>", "</div>", "&nbsp;", "<br>", "<br/>", "<br />"):
            continue
        if not line.strip():
            continue

        cleaned_lines.append(line.rstrip())

    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def split_sections(text):
    """按 Markdown 标题切分，返回 [(heading, body)]；首段 heading 为空。

    忽略代码块里的 "# 注释"，避免把示例代码当成标题。
    """
    sections = []
    heading = ""
    body = []
    in_fence = False

    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            body.append(line)
            continue

        if not in_fence:
            match = re.match(r"^(#{1,6})\s+(.*)$", line)
            if match:
                if heading or body:
                    sections.append((heading, "\n".join(body).strip()))
                heading = match.group(2).strip()
                body = []
                continue

        body.append(line)

    sections.append((heading, "\n".join(body).strip()))
    return sections


def _score_heading(heading):
    lowered = (heading or "").lower()
    score = 0
    for keyword, weight in SECTION_KEYWORDS:
        if keyword in lowered:
            score = max(score, weight)
    return score


def _truncate(text, limit):
    """按字符数截断，尽量在换行处断开。"""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    newline = cut.rfind("\n")
    if newline >= limit // 2:
        cut = cut[:newline]
    return cut.rstrip() + "\n\n…（README 已截断）"


def select_readme_sections(text, max_chars=MAX_README_CHARS):
    """按优先级选择 README 章节，并限制总长度。"""
    sections = split_sections(text)
    if not sections:
        return ""

    parts = []
    used = 0

    # 首段（项目介绍）最多占 1/3 预算，给功能/用法章节留空间
    first_heading, first_body = sections[0]
    intro = "\n\n".join(
        x for x in ((f"# {first_heading}" if first_heading else ""), first_body) if x
    )
    if intro:
        intro = _truncate(intro, max(500, max_chars // 3))
        parts.append(intro)
        used = len(intro)

    scored = []
    for index, (heading, body) in enumerate(sections[1:], start=1):
        scored.append((_score_heading(heading), index, heading, body))

    priority = sorted(
        [item for item in scored if item[0] > 0], key=lambda item: (-item[0], item[1])
    )
    others = [item for item in scored if item[0] == 0]

    for _, _, heading, body in priority + others:
        if used >= max_chars:
            break
        chunk = f"## {heading}\n{body}".strip() if body else f"## {heading}"
        chunk = _truncate(chunk, max_chars - used)
        if not chunk:
            break
        parts.append(chunk)
        used += len(chunk) + 2

    return "\n\n".join(parts)[:max_chars].strip()


def fetch_repo_context(full_name, max_chars=MAX_README_CHARS):
    """抓取仓库元数据 + README 摘要。

    返回 {"metadata": {...}, "readme_excerpt": "..."}；任何失败都只返回空字段。
    """
    if not parse_owner_repo(full_name):
        return {}

    metadata = fetch_repo_metadata(full_name)
    readme = fetch_readme(full_name)
    excerpt = select_readme_sections(clean_readme(readme), max_chars) if readme else ""

    if excerpt:
        print(f"  仓库上下文: {full_name} | README {len(readme)} 字符 -> 注入 {len(excerpt)} 字符")
    else:
        print(f"  仓库上下文: {full_name} | 未获取到可用的 README")

    return {"metadata": metadata, "readme_excerpt": excerpt}
