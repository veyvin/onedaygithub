import json
import requests
import os
from datetime import datetime
import re

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
    """将代码块转换为 HTML 格式"""
    # 处理 ```language\ncode\n``` 格式的代码块
    content = re.sub(
        r'```(\w+)?\s*\n(.*?)\n```',
        lambda m: f'<pre><code class="language-{m.group(1) or ""}">{m.group(2)}</code></pre>',
        content,
        flags=re.DOTALL
    )
    
    # 处理行内代码 `code`
    content = re.sub(r'`([^`]+)`', r'<code>\1</code>', content)
    
    return content

def extract_title_and_content(full_content):
    """从 API 返回的内容中提取标题和正文"""
    
    # 如果内容以 <!DOCTYPE 开头，说明返回了完整 HTML 文档
    if full_content.strip().startswith('<!DOCTYPE') or full_content.strip().startswith('<html'):
        # 使用 BeautifulSoup 解析 HTML
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(full_content, 'html.parser')
            
            # 提取标题 - 优先找 h1，如果没有就找 title
            title_tag = soup.find('h1')
            if title_tag:
                title = title_tag.get_text().strip()
            else:
                title_tag = soup.find('title')
                title = title_tag.get_text().strip() if title_tag else ""
            
            # 提取正文 - 找 body 或者直接取所有内容
            body_tag = soup.find('body')
            if body_tag:
                content = str(body_tag)
            else:
                content = full_content
                
            return title, content
            
        except ImportError:
            # 如果没有 BeautifulSoup，使用正则表达式简单处理
            print("警告: 未安装 BeautifulSoup，使用正则表达式提取内容")
            title_match = re.search(r'<title[^>]*>(.*?)</title>', full_content, re.IGNORECASE | re.DOTALL)
            title = title_match.group(1).strip() if title_match else ""
            
            body_match = re.search(r'<body[^>]*>(.*?)</body>', full_content, re.IGNORECASE | re.DOTALL)
            content = body_match.group(1) if body_match else full_content
            
            return title, content
    else:
        # 如果不是完整 HTML，尝试提取第一行作为标题
        lines = full_content.strip().split('\n')
        title = ""
        content = full_content
        
        # 找第一个有意义的行作为标题
        for line in lines:
            clean_line = line.strip()
            if clean_line and len(clean_line) < 100:  # 标题不会太长
                # 移除 HTML 标签
                clean_title = re.sub(r'<[^>]+>', '', clean_line)
                if clean_title and len(clean_title) > 5:
                    title = clean_title
                    break
        
        return title, content

def generate_post_with_deepseek(repo_data):
    """使用 DeepSeek API 生成博客文章"""
    
    # 从环境变量获取 API 密钥
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
    
    if not DEEPSEEK_API_KEY:
        print("错误: 未找到 DEEPSEEK_API_KEY 环境变量")
        print("请在 GitHub Secrets 中设置 DEEPSEEK_API_KEY")
        return None, None
    
    print(f"API Key 前几位: {DEEPSEEK_API_KEY[:10]}...")
    
    DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
    
    # 根据项目名称生成一个随机种子，用于选择不同的文章结构
    import hashlib
    seed = int(hashlib.md5(repo_data['name'].encode()).hexdigest()[:8], 16) % 6
    
    # 多样化的文章结构模板（根据 seed 选择不同的结构）
    structure_templates = [
        # 结构1: 故事型 - 从问题出发引出项目
        {
            "intro": "从一个实际开发场景或痛点开始，然后引出这个项目如何解决这个问题",
            "structure": ["引人入胜的开头（故事/问题场景）", "项目登场：如何解决这个问题", "核心功能深度解析", "技术亮点和创新点", "实战体验和使用建议", "总结：为什么值得关注"]
        },
        # 结构2: 对比型 - 与同类工具对比
        {
            "intro": "对比这个项目与同类工具/框架的差异，突出其独特价值",
            "structure": ["项目背景：为什么需要它", "与同类方案的对比分析", "核心优势解析", "技术实现亮点", "适用场景和局限性", "总结：什么时候选择它"]
        },
        # 结构3: 技术深度型 - 深入技术实现
        {
            "intro": "聚焦技术实现细节，适合技术导向的项目",
            "structure": ["项目概述和技术背景", "架构设计解析", "关键技术实现细节", "性能优化和设计亮点", "开发者视角的使用体验", "技术栈总结和启发"]
        },
        # 结构4: 场景驱动型 - 从应用场景出发
        {
            "intro": "从实际应用场景出发，展示项目的实用价值",
            "structure": ["实际应用场景介绍", "项目如何解决这些场景需求", "功能特性详解", "快速上手指南", "进阶使用技巧", "场景总结和扩展思考"]
        },
        # 结构5: 探索发现型 - 探索性分析
        {
            "intro": "以探索和发现的视角，逐步深入项目的各个方面",
            "structure": ["发现这个项目：第一印象", "深入探索：核心功能", "技术揭秘：实现原理", "实际测试：使用体验", "发现亮点：独特之处", "探索总结：值得学习的点"]
        },
        # 结构6: 问题解决型 - 从痛点出发
        {
            "intro": "从开发者常见的痛点出发，展示项目的解决方案",
            "structure": ["开发者痛点分析", "项目如何解决这些问题", "解决方案详解", "最佳实践和使用建议", "潜在问题和注意事项", "总结：解决问题的价值"]
        }
    ]
    
    selected_structure = structure_templates[seed]
    
    # 构建更灵活的提示词
    prompt = f"""
请为今天的 GitHub Trending 每日推荐项目写一篇技术博客文章。

项目信息：
- 项目名称：{repo_data['name']}
- 项目地址：{repo_data['url']}
- 项目描述：{repo_data['desc']}
- 推荐日期：{repo_data['date']}

🎯 写作策略（重要！）：
根据项目特点，选择最适合的文章结构。不要使用固定模板，要让每篇文章都有独特的风格和视角。

📝 文章结构建议（根据项目特点灵活选择3-6个部分）：
{selected_structure['intro']}

建议包含以下部分（但不要全部都用，根据项目特点选择3-5个即可）：
{chr(10).join(['- ' + s for s in selected_structure['structure']])}

⚠️ 注意：不要固定使用相同的结构！根据项目类型：
- 如果是框架/库：侧重技术实现和使用方法
- 如果是工具：侧重实用场景和效果
- 如果是 CLI 工具：侧重命令行体验和效率提升
- 如果是 UI/前端：侧重视觉效果和用户体验
- 如果是后端/基础设施：侧重架构设计和性能

✨ 写作要求：
1. 文章标题请直接写在第一行，不要包含任何 HTML 标签。标题要吸引人，包含项目名称和1-2个相关的有趣图标（如 🤖 🚀 🛠️ ⚡ 🎨 🔥 💡 📦 🌟 等）来标识这是自动生成的文章
2. 正文内容从第二行开始，使用 HTML 格式
3. 文章长度1000-2000字，要有实质内容，不要空泛
4. 正文中使用适当的 HTML 标签：<p>, <h2>, <h3>, <ul>, <li>, <code>, <strong>, <em>, <blockquote> 等
5. 所有标题标签必须包含 id 属性，例如：<h2 id="project-introduction">项目介绍</h2>
6. 不要返回完整的 HTML 文档结构（不要有 <!DOCTYPE>, <html>, <head>, <body> 标签）
7. 直接返回文章内容，不要有其他说明文字
8. 使用专业但易懂的技术语言，要有趣味性和可读性
9. 添加一些代码以增加可读性和趣味性，添加一些适当的图标如 📦 🚀 🛠️ 等以增加趣味性

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

请严格按照这个格式返回：
文章标题（第一行，不要HTML标签）
<html内容>（从第二行开始）
"""
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.7,
        "max_tokens": 8000,
        "stream": False
    }
    
    try:
        print("正在调用 DeepSeek API...")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        print(f"API 响应状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            raw_content = result['choices'][0]['message']['content']
            
            # 提取标题和内容
            title, content = extract_title_and_content(raw_content)
            
            # 如果提取失败，使用默认标题
            if not title:
                title = f"GitHub Trending 推荐：{repo_data['name']}"
            
            # 格式化代码块 - 将 ``` 转换为 HTML
            content = format_code_blocks(content)
            
            print(f"提取的标题: {title}")
            print(f"内容预览: {content[:100]}...")
            
            return title, content
        else:
            print(f"DeepSeek API 错误: {response.status_code}")
            print(f"错误详情: {response.text}")
            return None, None
            
    except requests.exceptions.RequestException as e:
        print(f"网络请求错误: {e}")
        return None, None

def _derive_tags_from_repo(repo_data: dict) -> list[str]:
    """
    根据仓库信息推导额外标签（可选）。
    可从项目名、描述中提取技术关键词，用于丰富标签。
    """
    tags = []
    name = (repo_data.get("name") or "").lower()
    desc = (repo_data.get("desc") or "").lower()
    # 常见技术关键词
    keywords = ["python", "rust", "javascript", "typescript", "go", "java", "ai", "llm", "quant", "trading", "cli", "web"]
    for kw in keywords:
        if kw in name or kw in desc:
            tags.append(kw.capitalize())
    return tags[:3]  # 最多 3 个推导标签


def save_generated_post(title, content, repo_data, categories=None, tags=None):
    """
    保存生成的文章。
    categories: 可选，分类列表，如 ["GitHub Trending", "开源项目"]
    tags: 可选，标签列表。若不传则使用默认 + 从 repo 推导的标签
    """
    # 默认分类
    final_categories = categories or ["GitHub Trending", "开源项目"]
    # 默认标签 + 从仓库推导的标签
    default_tags = ["GitHub", "Trending", "开源项目", "每日推荐", "自动发布", "自动化"]
    derived = _derive_tags_from_repo(repo_data)
    final_tags = tags if tags is not None else (default_tags + [t for t in derived if t not in default_tags])

    post_data = {
        "title": title,
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
        
    print(f"处理项目: {repo_data['name']}")
    
    # 生成文章
    title, content = generate_post_with_deepseek(repo_data)
    
    if title and content:
        # 保存生成的文章
        save_generated_post(title, content, repo_data)
        print("文章生成成功！")
        print(f"标题: {title}")
        print(f"文章长度: {len(content)} 字符")
    else:
        print("文章生成失败")
        exit(1)