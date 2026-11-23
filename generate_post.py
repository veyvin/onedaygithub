import json
import requests
import os
import hashlib
import html
import re
import traceback
from datetime import datetime

# BeautifulSoup 是必需依赖（见 requirements.txt），但保留可选降级路径
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
    print("警告: 未安装 BeautifulSoup，HTML 解析将退化为正则表达式")

from repo_context import fetch_repo_context


# Python 的 re 不支持 \p{Emoji}，用码位区间覆盖常见 emoji
EMOJI_RE = re.compile(
    "["
    "←-⇿"          # 箭头
    "⌀-⏿"          # 各类技术符号
    "①-⓿"          # 带圈数字
    "■-➿"          # 几何图形 + 杂项符号 + 装饰符号（⚡ ⚖️ 等）
    "⬀-⯿"          # 杂项符号与箭头补充
    "\U0001F004"
    "\U0001F0CF"
    "\U0001F170-\U0001F251"
    "〰〽㊗㊙"
    "\U0001F1E6-\U0001F1FF"  # 国旗（区域指示符）
    "\U0001F300-\U0001F5FF"  # 符号与象形文字
    "\U0001F600-\U0001F64F"  # 表情符号
    "\U0001F680-\U0001F6FF"  # 交通与地图符号（🛠️ 🚀 等）
    "\U0001F700-\U0001F77F"
    "\U0001F900-\U0001F9FF"  # 补充符号与象形文字（🧭 💡 等）
    "\U0001FA00-\U0001FAFF"  # 符号与象形文字扩展 A
    "️"                # 变体选择符 VS16
    "‍"                # 零宽连接符 ZWJ
    "]+"
)


def strip_emoji(text):
    """去掉标题中的 emoji / 装饰符号，得到公众号可用的纯文字标题。

    站内（Halo）标题保留 emoji，这里只产出备用标题，不影响原标题。
    """
    if not text:
        return ""
    cleaned = EMOJI_RE.sub("", str(text))
    cleaned = re.sub(r"\s+", " ", cleaned)
    # 删掉 emoji 后可能残留的悬空标点/空白，例如 "🚀 Foo 🛠️" -> "Foo"
    cleaned = re.sub(r"^[\s\-–—|:：,，、·]+", "", cleaned)
    cleaned = re.sub(r"[\s\-–—|:：,，、·]+$", "", cleaned)
    return cleaned.strip()


def strip_leading_title(content, title):
    """去掉正文中与文章标题重复的开头内容。

    两种来源：
    - 模型把标题写在第一行纯文本（非完整 HTML 路径）；
    - 完整 HTML 路径下 <h1> 标题仍留在 body 里。
    两者都会让标题在页面上显示两次。
    """
    if not content:
        return content

    body = content.strip()
    title_norm = re.sub(r"\s+", "", title or "")
    if not title_norm:
        return body

    # 1) 开头的 <h1>…</h1>
    h1 = re.match(r"^<h1[^>]*>(.*?)</h1>\s*", body, re.IGNORECASE | re.DOTALL)
    if h1:
        h1_text = re.sub(r"<[^>]+>", "", h1.group(1)).strip()
        if re.sub(r"\s+", "", h1_text) == title_norm:
            return body[h1.end():].strip() or body

    # 2) 开头的纯文本标题行（允许中间夹空行）
    lines = body.split("\n")
    for i, line in enumerate(lines[:3]):
        plain = re.sub(r"<[^>]+>", "", line).strip()
        if not plain:
            continue
        if re.sub(r"\s+", "", plain) == title_norm:
            return "\n".join(lines[i + 1:]).strip() or body
        break

    return body

def read_repo_data():
    """读取 GitHub Trending 数据"""
    try:
        with open('github_daily.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("github_daily.json 文件不存在")
        return None
    except json.JSONDecodeError:
        print("github_daily.json 文件格式错误")
        return None

def format_code_blocks(content):
    """将代码块转换为 HTML 格式。

    - 代码内容做 HTML 转义，避免 HTML/JSX 示例被浏览器当成真实标签渲染；
    - 先占位围栏代码块，再处理行内代码，避免代码里的反引号被二次替换成嵌套 <code>。
    """
    if not content:
        return content

    blocks = []

    def _stash_block(match):
        lang = match.group(1) or ""
        # quote=False：只转义 & < >，保留代码里的引号原样
        code = html.escape(match.group(2), quote=False)
        blocks.append(f'<pre><code class="language-{lang}">{code}</code></pre>')
        return f"\x00CODEBLOCK{len(blocks) - 1}\x00"

    content = re.sub(
        r'```(\w+)?\s*\n(.*?)\n```',
        _stash_block,
        content,
        flags=re.DOTALL
    )

    # 行内代码：同样转义，防止 `<T>` 之类被解析成标签
    content = re.sub(
        r'`([^`\n]+)`',
        lambda m: f'<code>{html.escape(m.group(1), quote=False)}</code>',
        content
    )

    for i, block in enumerate(blocks):
        content = content.replace(f"\x00CODEBLOCK{i}\x00", block)

    return content

def extract_title_and_content(full_content):
    """从 API 返回的内容中提取标题和正文"""
    stripped = full_content.strip()

    # 如果内容以 <!DOCTYPE 开头，说明返回了完整 HTML 文档
    if stripped.startswith('<!DOCTYPE') or stripped.startswith('<html'):
        if BeautifulSoup is not None:
            # 使用 BeautifulSoup 解析 HTML
            soup = BeautifulSoup(full_content, 'html.parser')

            # 提取标题 - 优先找 h1，如果没有就找 title
            title_tag = soup.find('h1')
            if title_tag:
                title = title_tag.get_text().strip()
            else:
                title_tag = soup.find('title')
                title = title_tag.get_text().strip() if title_tag else ""

            # 提取正文 - 只要 body 内部内容，避免把 <body> 标签嵌进 Halo 文章正文
            body_tag = soup.find('body')
            content = body_tag.decode_contents() if body_tag else full_content

            return title, content
        else:
            # 没有安装 BeautifulSoup，使用正则表达式简单处理
            print("警告: 未安装 BeautifulSoup，使用正则表达式提取内容")
            title_match = re.search(r'<title[^>]*>(.*?)</title>', full_content, re.IGNORECASE | re.DOTALL)
            title = title_match.group(1).strip() if title_match else ""

            body_match = re.search(r'<body[^>]*>(.*?)</body>', full_content, re.IGNORECASE | re.DOTALL)
            content = body_match.group(1) if body_match else full_content

            return title, content


    # 非完整 HTML：尝试提取第一行作为标题
    lines = full_content.strip().split('\n')
    title = ""
    title_index = -1

    # 找第一个有意义的行作为标题
    for i, line in enumerate(lines):
        clean_line = line.strip()
        if clean_line and len(clean_line) < 100:  # 标题不会太长
            # 移除 HTML 标签
            clean_title = re.sub(r'<[^>]+>', '', clean_line)
            if clean_title and len(clean_title) > 5:
                title = clean_title
                title_index = i
                break

    # 标题行不属于正文：正文从标题之后开始，否则页面上标题会出现两次
    if title_index >= 0:
        content = '\n'.join(lines[title_index + 1:]).strip()
    else:
        content = full_content

    return title, content

# 默认模型提供商。DEFAULT_MODEL_NAME 只对这个提供商生效，避免切换提供商时串用模型。
DEFAULT_PROVIDER = "sub2api"

# 单次 LLM 请求超时（秒）。目标 2500-5000 字，生成时间比短文更长，留足余量。
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "240"))

# 单次输出 token 上限：2500-5000 字中文 + HTML 标记约 7k-10k tokens，留足余量。
MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "20000"))

# 正文纯文字长度要求（不含 HTML 标签与代码块）
MIN_ARTICLE_CHARS = int(os.getenv("ARTICLE_MIN_CHARS", "2500"))
MAX_ARTICLE_CHARS = int(os.getenv("ARTICLE_MAX_CHARS", "5000"))

# 模型提供商配置
PROVIDERS = {
    "deepseek": {
        "api_url": "https://api.deepseek.com/chat/completions",
        "api_key_env": "DEEPSEEK_API_KEY",
        "model": "deepseek-v4-flash",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
    "opencode-zen": {
        "api_url": "https://opencode.ai/zen/v1/chat/completions",
        "api_key_env": "OPENCODE_ZEN_API_KEY",
        "model": "big-pickle",
        "auth_header": "x-api-key",
        "auth_prefix": "",
    },
    "cursor": {
        "api_key_env": "CURSOR_API_KEY",
        "model": "composer-2.5",
        "use_sdk": True,
    },
    "sub2api": {
        "api_url_env": "SUB2API_API_URL",
        "api_url_default": "http://localhost:18080/v1/chat/completions",
        "api_key_env": "SUB2API_API_KEY",
        "model": "deepseek-v4.1-flash",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
    "commandcode": {
        "api_url": "https://api.commandcode.ai/provider/v1/chat/completions",
        "api_key_env": "COMMANDCODE_API_KEY",
        "model": "deepseek/deepseek-v4-flash",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
}


def _resolve_model(provider, provider_name=None):
    """解析实际使用的模型名。

    优先级：
    1. MODEL_NAME：显式指定，对所有提供商生效（手动 Run workflow 时填写）；
    2. DEFAULT_MODEL_NAME：只对默认提供商生效（来自仓库 Variables/Secrets），
       避免切换到 deepseek 等提供商时继续发送 sub2api 的模型名；
    3. provider 自带的默认模型。
    """
    explicit = os.getenv('MODEL_NAME', '').strip()
    if explicit:
        return explicit
    if provider_name == DEFAULT_PROVIDER:
        default_override = os.getenv('DEFAULT_MODEL_NAME', '').strip()
        if default_override:
            return default_override
    return provider.get('model')


# 固定写作规则单独放 system：每天项目信息不同，若写在 prompt 开头会导致前缀缓存永远 miss。
WRITING_SYSTEM_PROMPT = """你是技术博客作者。请为用户给出的开源项目写一篇技术博客文章。仅基于用户消息中的真实信息写作，不要编造未提供的技术细节、数据或对比。

🎯 写作策略（重要！）：
根据项目特点，选择最适合的文章结构。不要使用固定模板，要让每篇文章都有独特的风格和视角。

⚠️ 注意：不要固定使用相同的结构！根据项目类型：
- 如果是框架/库：侧重技术实现和使用方法
- 如果是工具：侧重实用场景和效果
- 如果是 CLI 工具：侧重命令行体验和效率提升
- 如果是 UI/前端：侧重视觉效果和用户体验
- 如果是后端/基础设施：侧重架构设计和性能

✨ 写作要求：
1. 文章标题请直接写在第一行，不要包含任何 HTML 标签。标题要吸引人，包含项目名称和1-2个相关的有趣图标（如 🤖 🚀 🛠️ ⚡ 🎨 🔥 💡 📦 🌟 等）来标识这是自动生成的文章
2. 正文内容从第二行开始，使用 HTML 格式
3. 正文纯文字 2500-5000 字（不含 HTML 标签与代码块），分 5-8 个小节，每节 500-800 字，要有实质内容，不要空泛
4. 正文中使用适当的 HTML 标签：<p>, <h2>, <h3>, <ul>, <li>, <code>, <strong>, <em>, <blockquote> 等
5. 所有标题标签必须包含 id 属性，例如：<h2 id="project-introduction">项目介绍</h2>
6. 不要返回完整的 HTML 文档结构（不要有 <!DOCTYPE>, <html>, <head>, <body> 标签）
7. 直接返回文章内容，不要有其他说明文字
8. 使用专业但易懂的技术语言，要有趣味性和可读性
9. 添加一些代码以增加可读性和趣味性，添加一些适当的图标如 📦 🚀 🛠️ 等以增加趣味性
10. 不要提及项目来自哪个榜单、排名或趋势信息，也不要解释项目的来源
11. 不要出现描述缺失的占位词，也不要围绕"没有描述/零描述"做评论或玩梗；信息不足时如实说明

🖼️ 图片生成要求（如果模型支持图片输出）：
- 如果你的模型支持生成图片，请在文章中适当位置（通常 2-3 处）生成与文章内容紧密相关的配图
- 图片应帮助读者理解文章内容，例如：项目架构图、流程示意图、使用场景演示、功能对比图等
- 不要生成纯装饰性图片，每张图都应有实际的信息价值
- 图片应使用标准 HTML 标签插入：<img alt="图片描述文字" src="图片URL或base64数据" />
- alt 属性必须填写，用一句话描述图片内容，方便无图环境理解
- 如果模型不支持图片生成，则忽略此要求，仅生成纯文本文章即可

🎨 增加趣味性的建议：
- 开头可以用一个有趣的故事、场景或问题引入
- 适当使用技术梗、开发趣事或生动的比喻
- 添加一些开发者会有共鸣的细节
- 使用生动的例子和场景描述
- 在合适的地方添加表情符号（但不要过度使用）

💻 代码格式要求：
- 所有代码块必须使用 <pre><code> 标签包裹
- 不要使用 ``` 来包裹代码块
- 行内代码使用 <code> 标签
- 代码要有适当的缩进和语法高亮提示（class="language-xxx"）

示例正确的格式：
<pre><code class="language-python">
class Example:
    def method(self):
        return "Hello World"
</code></pre>

行内代码示例：使用 <code>console.log()</code> 进行调试。

🔄 文章结构多样性要求：
- 不同项目应该有不同的文章结构
- 不要总是用相同的段落顺序
- 可以根据项目特点调整重点（比如有些项目适合先讲技术，有些适合先讲场景）
- 标题要多样，不要总是"项目介绍"、"功能特点"这种固定词汇

请只返回一个 JSON 对象（不要使用 ``` 包裹，不要输出任何解释文字），字段如下：
{
  "title": "文章标题，可含 1-2 个 emoji，不要 HTML 标签，不超过 64 字",
  "summary": "80-120 字纯文本摘要，用于文章列表与公众号导语，不要 HTML",
  "tags": ["最多 3 个技术标签"],
  "content": "HTML 正文，从 <p> 开始，不要包含 <html>/<body>/<h1> 标签"
}
"""


def _build_user_prompt(repo_data, repo_context=None):
    """每天会变的项目信息 + 本次结构建议，放在 user 消息末尾，不影响 system 前缀缓存。"""
    name = repo_data.get('name')
    url = repo_data.get('url')
    raw_desc = repo_data.get('desc')
    desc = raw_desc.strip() if isinstance(raw_desc, str) and raw_desc.strip() else ''
    if desc.lower() in ('no description', 'no description provided', 'none'):
        desc = ''
    desc_display = desc if desc else '（项目未提供描述）'
    date = repo_data.get('date')

    context = repo_context or {}
    metadata = context.get('metadata') or {}
    readme_excerpt = (context.get('readme_excerpt') or '').strip()

    language = repo_data.get('language') or metadata.get('language') or ''
    stars = repo_data.get('stars') or metadata.get('stars')
    today_stars = repo_data.get('today_stars')
    topics = metadata.get('topics') or []

    facts = []
    if stars not in (None, '', 'N/A'):
        facts.append(f"- Star 数：{stars}")
    if language:
        facts.append(f"- 主要语言：{language}")
    if today_stars and today_stars != 'N/A':
        facts.append(f"- 区间新增：{today_stars}")
    if topics:
        topics_text = ', '.join(str(t) for t in topics[:10])
        facts.append(f"- Topics：{topics_text}")
    facts_block = "\n".join(facts)

    readme_block = ""
    if readme_excerpt:
        readme_block = (
            "\nREADME 摘要（唯一事实来源：以下内容来自仓库 README；"
            "未出现的信息不要编造，不要引用未提供的性能数据、版本号或对比）：\n"
            f"{readme_excerpt}\n"
        )

    seed = int(hashlib.md5((name or '').encode()).hexdigest()[:8], 16) % 6

    # 榜单来源：全球日榜抓完后会自动降级到中文区/周榜等来源，
    # 在提示词里注明，文章才不会把周榜项目写成「今日新增」。
    source_label = repo_data.get('source_label')
    period = repo_data.get('period')
    if source_label:
        period_text = {'daily': '日榜（当日新增）', 'weekly': '周榜（当周累计）'}.get(period, period or '')
        source_line = f"- 榜单来源：{source_label}" + (f"（{period_text}）" if period_text else "") + "\n"
    else:
        source_line = ""

    structure_templates = [
        {
            "intro": "从一个实际开发场景或痛点开始，然后引出这个项目如何解决这个问题",
            "structure": ["引人入胜的开头（故事/问题场景）", "项目登场：如何解决这个问题", "核心功能深度解析", "技术亮点和创新点", "实战体验和使用建议", "上手前的准备与安装步骤", "适用边界与替代方案", "总结：为什么值得关注"]
        },
        {
            "intro": "对比这个项目与同类工具/框架的差异，突出其独特价值",
            "structure": ["项目背景：为什么需要它", "与同类方案的对比分析", "核心优势解析", "技术实现亮点", "迁移成本与上手难度", "适用场景和局限性", "团队选型 checklist", "总结：什么时候选择它"]
        },
        {
            "intro": "聚焦技术实现细节，适合技术导向的项目",
            "structure": ["项目概述和技术背景", "架构设计解析", "关键模块拆解", "关键技术实现细节", "性能优化和设计亮点", "踩坑记录与调试技巧", "开发者视角的使用体验", "技术栈总结和启发"]
        },
        {
            "intro": "从实际应用场景出发，展示项目的实用价值",
            "structure": ["实际应用场景介绍", "项目如何解决这些场景需求", "功能特性详解", "快速上手指南", "进阶使用技巧", "真实案例拆解", "扩展与生态集成", "场景总结和扩展思考"]
        },
        {
            "intro": "以探索和发现的视角，逐步深入项目的各个方面",
            "structure": ["发现这个项目：第一印象", "深入探索：核心功能", "技术揭秘：实现原理", "上手实测记录", "实际测试：使用体验", "社区与生态观察", "发现亮点：独特之处", "探索总结：值得学习的点"]
        },
        {
            "intro": "从开发者常见的痛点出发，展示项目的解决方案",
            "structure": ["开发者痛点分析", "项目如何解决这些问题", "解决方案详解", "最佳实践和使用建议", "落地路线图", "潜在问题和注意事项", "常见问题排查", "总结：解决问题的价值"]
        }
    ]

    selected_structure = structure_templates[seed]

    return f"""请为今天的热门开源项目写一篇技术博客文章。

项目信息（仅基于以下真实信息写作，不要编造未提供的技术细节、数据或对比）：
- 项目名称：{name}
- 项目地址：{url}
- 项目描述：{desc_display}
- 推荐日期：{date}
{source_line}{facts_block}
{readme_block}
📝 本次文章结构建议（根据项目特点灵活选择 5-8 个部分，每节 500-800 字）：
{selected_structure['intro']}

建议包含以下部分（但不要全部都用，根据项目特点选择 5-8 个即可）：
{chr(10).join(['- ' + s for s in selected_structure['structure']])}
"""


def _build_prompt(repo_data, repo_context=None):
    """兼容测试与 Cursor SDK：system + user 拼成单条文本。"""
    return WRITING_SYSTEM_PROMPT + "\n\n" + _build_user_prompt(repo_data, repo_context)


def _log_completion_usage(result):
    """打印 prompt 缓存命中情况（DeepSeek / OpenAI / Anthropic 字段都认）。"""
    usage = result.get("usage") if isinstance(result, dict) else None
    if not isinstance(usage, dict):
        print("API usage: 响应未返回 usage")
        return

    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    cache_hit = (
        usage.get("prompt_cache_hit_tokens")
        or usage.get("cache_read_input_tokens")
        or details.get("cached_tokens")
        or 0
    )
    cache_miss = (
        usage.get("prompt_cache_miss_tokens")
        or usage.get("cache_creation_input_tokens")
    )
    print(
        f"API usage: prompt={prompt_tokens} completion={completion_tokens} "
        f"cache_hit={cache_hit} cache_miss={cache_miss if cache_miss is not None else 'n/a'}"
    )
    if not cache_hit:
        print("提示: 本次未命中 prompt 缓存。同一 system 前缀在缓存有效期内再次请求才会命中。")


def _parse_structured_post(raw):
    """解析模型返回的 JSON 文章；失败返回 None。

    兼容三种常见返回：纯 JSON、```json 围栏、JSON 前后夹带说明文字。
    """
    if not raw:
        return None

    text = raw.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None

    try:
        data = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None

    if not isinstance(data, dict):
        return None

    title = str(data.get("title") or "").strip()
    content = str(data.get("content") or "").strip()
    if not title or not content:
        return None

    summary = str(data.get("summary") or "").strip()
    tags = []
    raw_tags = data.get("tags")
    if isinstance(raw_tags, list):
        for tag in raw_tags:
            tag = str(tag).strip()
            if tag and tag not in tags:
                tags.append(tag)

    return {"title": title, "summary": summary, "tags": tags[:5], "content": content}


def _plain_text_length(content):
    """统计正文纯文字长度：去掉 HTML 标签、代码块与空白。"""
    if not content:
        return 0
    if BeautifulSoup is not None:
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup.find_all(["pre", "code", "script", "style"]):
            tag.decompose()
        text = soup.get_text("")
    else:
        text = re.sub(r"<[^>]+>", "", content)
    return len(re.sub(r"\s+", "", text))


def _validate_post(post):
    """校验生成结果，返回问题列表（空列表表示通过）。"""
    problems = []
    title = (post.get("title") or "").strip()
    content = (post.get("content") or "").strip()

    if len(title) < 5:
        problems.append("标题过短")
    if len(title) > 80:
        problems.append("标题过长（超过 80 字）")

    plain_len = _plain_text_length(content)
    if plain_len < MIN_ARTICLE_CHARS:
        problems.append(f"正文纯文字不足 {MIN_ARTICLE_CHARS} 字（当前 {plain_len} 字）")
    if plain_len > MAX_ARTICLE_CHARS:
        problems.append(f"正文纯文字超过 {MAX_ARTICLE_CHARS} 字（当前 {plain_len} 字）")

    lowered = content.lower()
    if any(tag in lowered for tag in ("<!doctype", "<html", "<body")):
        problems.append("正文包含完整 HTML 文档结构")
    if "```" in content:
        problems.append("正文仍包含 Markdown 代码围栏")
    if any(placeholder in lowered for placeholder in ("no description", "没有描述")):
        problems.append("正文包含描述缺失的占位词")

    return problems


def _call_chat_completion(provider_name, api_url, headers, model, messages):
    """调用 Chat Completions，返回 (原始文本, 响应 JSON)；失败返回 (None, None)。"""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "stream": False,
    }

    try:
        print(f"正在调用 {provider_name} API（system 前缀可缓存）...")
        response = requests.post(api_url, headers=headers, json=payload, timeout=LLM_TIMEOUT)
        print(f"API 响应状态码: {response.status_code}")

        if response.status_code != 200:
            print(f"API 错误: {response.status_code}")
            print(f"错误详情: {response.text[:500]}")
            return None, None

        try:
            result = response.json()
            raw_content = result['choices'][0]['message']['content']
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            # 代理偶尔会返回 200 + 错误 JSON，这里给出可读报错而不是直接 traceback
            print(f"API 响应解析失败: {exc}")
            print(f"响应预览: {response.text[:500]}")
            return None, None

        return raw_content, result

    except requests.exceptions.RequestException as exc:
        print(f"网络请求错误: {exc}")
        return None, None


def generate_post_with_cursor_sdk(repo_data, provider, repo_context=None):
    """使用 Cursor Python SDK 生成博客文章（直接调用，无需代理）"""
    api_key = os.getenv(provider['api_key_env'])
    if not api_key:
        print(f"错误: 未找到 {provider['api_key_env']} 环境变量")
        print(f"请在 GitHub Secrets 中设置 {provider['api_key_env']}")
        return None, None, None

    name = repo_data.get('name')
    url = repo_data.get('url')
    date = repo_data.get('date')
    if not name or not url or not date:
        print(f"错误: repo_data 缺少必需字段 (name/url/date): {repo_data}")
        return None, None, None

    model = _resolve_model(provider, 'cursor')
    print(f"模型提供商: cursor | 模型: {model} | API Key 长度: {len(api_key)}")

    prompt = _build_prompt(repo_data, repo_context)

    try:
        from cursor_sdk import Agent, CloudAgentOptions
    except ImportError:
        print("错误: 未安装 cursor-sdk 包，请运行 pip install cursor-sdk")
        return None, None, None

    try:
        print("正在调用 Cursor SDK...")
        # 使用无仓库的云端 Agent，仅用于文本生成
        with Agent.create(
            model=model,
            api_key=api_key,
            cloud=CloudAgentOptions(repos=[]),
        ) as agent:
            run = agent.send(prompt)
            raw_content = run.wait().text()

        post = _parse_structured_post(raw_content)
        if post is None:
            print("未能解析结构化 JSON，回退到标题/正文启发式提取")
            title, content = extract_title_and_content(raw_content)
            post = {"title": title or f"{name}：项目解析", "summary": "", "tags": [], "content": content}

        post["content"] = strip_leading_title(format_code_blocks(post["content"]), post["title"])

        print(f"提取的标题: {post['title']}")
        print(f"内容预览: {post['content'][:100]}...")

        return post["title"], post["content"], {
            "summary": post.get("summary", ""),
            "tags": post.get("tags", []),
        }
    except Exception as e:
        print(f"Cursor SDK 错误: {e}")
        traceback.print_exc()
        return None, None, None


def _generate_post_from_messages(repo_data, provider_name, api_url, headers, model,
                                 user_prompt, name):
    """调用模型并校验结果；校验失败时带错误信息重试一次。"""
    messages = [
        {"role": "system", "content": WRITING_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    for attempt in range(2):
        raw_content, result = _call_chat_completion(
            provider_name, api_url, headers, model, messages
        )
        if raw_content is None:
            return None, None, None

        _log_completion_usage(result)

        post = _parse_structured_post(raw_content)
        if post is None:
            print("未能解析结构化 JSON，回退到标题/正文启发式提取")
            title, content = extract_title_and_content(raw_content)
            post = {"title": title or f"{name}：项目解析", "summary": "", "tags": [], "content": content}

        post["content"] = strip_leading_title(format_code_blocks(post["content"]), post["title"])

        problems = _validate_post(post)
        if problems and attempt == 0:
            print(f"文章校验未通过，准备重试: {'；'.join(problems)}")
            messages.append({"role": "assistant", "content": raw_content})
            messages.append({
                "role": "user",
                "content": (
                    f"上一次输出未通过校验：{'；'.join(problems)}。"
                    "请重新输出完整 JSON，不要输出任何解释文字。"
                ),
            })
            continue

        if problems:
            print(f"文章校验未通过（已重试仍失败，继续发布）: {'；'.join(problems)}")

        print(f"提取的标题: {post['title']}")
        print(f"内容预览: {post['content'][:100]}...")
        return post["title"], post["content"], {
            "summary": post.get("summary", ""),
            "tags": post.get("tags", []),
        }

    return None, None, None


def generate_post_with_deepseek(repo_data, repo_context=None):
    """使用大模型 API 生成博客文章（默认 Sub2API，另支持 DeepSeek、OpenCode Zen、Cursor SDK）"""

    provider_name = os.getenv('MODEL_PROVIDER', DEFAULT_PROVIDER)
    provider = PROVIDERS.get(provider_name)
    if not provider:
        print(f"错误: 未知的 MODEL_PROVIDER '{provider_name}'，可选: {list(PROVIDERS.keys())}")
        return None, None, None

    # Cursor SDK 走单独的代码路径
    if provider.get('use_sdk'):
        return generate_post_with_cursor_sdk(repo_data, provider, repo_context)

    # 从环境变量获取 API 密钥
    api_key = os.getenv(provider['api_key_env'])

    if not api_key:
        print(f"错误: 未找到 {provider['api_key_env']} 环境变量")
        print(f"请在 GitHub Secrets 中设置 {provider['api_key_env']}")
        return None, None, None

    # 仅打印长度用于诊断，避免泄露 API Key 内容
    model = _resolve_model(provider, provider_name)
    print(f"模型提供商: {provider_name} | 模型: {model} | API Key 长度: {len(api_key)}")

    # 验证仓库必需字段，避免 KeyError 导致整段失败
    name = repo_data.get('name')
    url = repo_data.get('url')
    date = repo_data.get('date')
    if not name or not url or not date:
        print(f"错误: repo_data 缺少必需字段 (name/url/date): {repo_data}")
        return None, None, None

    API_URL = os.getenv(provider.get('api_url_env', ''), provider.get('api_url_default', provider.get('api_url', '')))

    user_prompt = _build_user_prompt(repo_data, repo_context)

    headers = {
        "Content-Type": "application/json",
        provider['auth_header']: f"{provider['auth_prefix']}{api_key}"
    }

    return _generate_post_from_messages(
        repo_data, provider_name, API_URL, headers, model, user_prompt, name
    )

def _derive_tags_from_repo(repo_data: dict) -> list[str]:
    """
    根据仓库信息推导额外标签（可选）。

    使用词元/词边界匹配，避免子串误判：
    - django 不应命中 go
    - daily 不应命中 ai
    - javascript 不应同时命中 java
    """
    name = (repo_data.get("name") or "").lower()
    desc = (repo_data.get("desc") or "").lower()
    text = f"{name} {desc}".replace("-", " ").replace("_", " ")

    # 标签名 + 词边界正则（按顺序匹配，最多取 3 个）
    keywords = [
        ("Python", r"\bpython\b"),
        ("Rust", r"\brust\b"),
        ("JavaScript", r"\bjavascript\b"),
        ("TypeScript", r"\btypescript\b"),
        ("Go", r"\b(go|golang)\b"),
        ("Java", r"\bjava\b"),
        ("AI", r"\b(ai|artificial intelligence)\b"),
        ("LLM", r"\bllms?\b"),
        ("Quant", r"\bquant\b"),
        ("Trading", r"\btrading\b"),
        ("CLI", r"\bcli\b"),
        ("Web", r"\bweb\b"),
    ]
    tags = []
    for tag, pattern in keywords:
        if re.search(pattern, text, re.IGNORECASE):
            tags.append(tag)
    return tags[:3]  # 最多 3 个推导标签


def save_generated_post(title, content, repo_data, categories=None, tags=None,
                        summary=None, extra_tags=None):
    """
    保存生成的文章。
    categories: 可选，分类列表，如 ["GitHub Trending", "开源项目"]
    tags: 可选，标签列表。若不传则使用默认 + 从 repo 推导的标签
    summary: 可选，模型生成的文章摘要（用于 Halo 列表导语）
    extra_tags: 可选，模型生成的技术标签，会与推导标签合并去重
    """
    # 默认分类
    final_categories = categories or ["GitHub Trending", "开源项目"]
    # 默认标签 + 从仓库推导的标签
    default_tags = ["GitHub", "Trending", "开源项目", "每日推荐", "自动发布", "自动化"]
    derived = _derive_tags_from_repo(repo_data)
    final_tags = tags if tags is not None else list(default_tags)

    if tags is None:
        for tag in list(derived) + list(extra_tags or []):
            if tag and tag not in final_tags:
                final_tags.append(tag)

    post_data = {
        "title": title,
        # 站内标题保留 emoji；这份纯文字标题供公众号/投稿使用
        "title_clean": strip_emoji(title),
        "summary": (summary or "").strip(),
        "content": content,
        "repo_info": repo_data,
        "categories": final_categories,
        "tags": final_tags,
        "generated_at": datetime.now().isoformat()
    }

    with open('generated_post.json', 'w', encoding='utf-8') as f:
        json.dump(post_data, f, ensure_ascii=False, indent=2)

    print("文章已生成并保存到 generated_post.json")

if __name__ == "__main__":
    # 读取仓库数据
    repo_data = read_repo_data()
    if not repo_data:
        print("无法读取仓库数据，退出")
        exit(1)
        
    print(f"处理项目: {repo_data.get('name', 'unknown')}")

    # 抓取仓库元数据与 README，作为文章的事实来源（失败不影响生成）
    repo_context = fetch_repo_context(repo_data.get('name'))
    
    # 生成文章
    title, content, meta = generate_post_with_deepseek(repo_data, repo_context)
    
    if title and content:
        # 保存生成的文章
        save_generated_post(
            title, content, repo_data,
            summary=(meta or {}).get('summary'),
            extra_tags=(meta or {}).get('tags'),
        )
        print("文章生成成功！")
        print(f"标题: {title}")
        print(f"公众号标题（无 emoji）: {strip_emoji(title)}")
        print(f"文章长度: {len(content)} 字符")
    else:
        print("文章生成失败")
        exit(1)
