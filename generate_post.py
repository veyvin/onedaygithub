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
    
    # 构建更明确的提示词
    prompt = f"""
请为今天的 GitHub Trending 每日推荐项目写一篇技术博客文章。

项目信息：
- 项目名称：{repo_data['name']}
- 项目地址：{repo_data['url']}
- 项目描述：{repo_data['desc']}
- 推荐日期：{repo_data['date']}

写作要求：
1. 文章标题请直接写在第一行，不要包含任何 HTML 标签,添加图标来区分这篇文章是自动生成的
2. 正文内容从第二行开始，使用 HTML 格式
3. 文章长度800-1200字
4. 内容结构建议：
   - 项目介绍和背景
   - 主要功能特点分析
   - 技术架构推测
   - 应用场景和价值
   - 总结和展望
5. 正文中使用适当的 HTML 标签：<p>, <h2>, <h3>, <ul>, <li>, <code>, <strong> 等
6. 不要返回完整的 HTML 文档结构（不要有 <!DOCTYPE>, <html>, <head>, <body> 标签）
7. 直接返回文章内容，不要有其他说明文字
8. 添加一些代码以增加可读性和趣味性，添加一些适当的图标如 📦 🚀 🛠️ 等以增加趣味性
9. 文章标题要吸引人，包含项目名称
10. 使用专业但易懂的技术语言

🔥 重要代码格式要求：
- 所有代码块必须使用 <pre><code> 标签包裹
- 不要使用 ``` 来包裹代码块
- 行内代码使用 <code> 标签
- 代码要有适当的缩进和语法高亮提示

示例正确的格式：
<pre><code class="language-python">
class Example:
    def method(self):
        return "Hello World"
</code></pre>

行内代码示例：使用 <code>console.log()</code> 进行调试。

请严格按照这个格式返回：
文章标题
<html内容>
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

def save_generated_post(title, content, repo_data):
    """保存生成的文章"""
    post_data = {
        "title": title,
        "content": content,
        "repo_info": repo_data,
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