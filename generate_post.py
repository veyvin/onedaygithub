import json
import requests
import os
from datetime import datetime

def read_repo_data():
    """读取 GitHub Trending 数据"""
    with open('github_daily.json', 'r', encoding='utf-8') as f:
        return json.load(f)

def generate_post_with_deepseek(repo_data):
    """使用 DeepSeek API 生成博客文章"""
    
    # DeepSeek API 配置
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
    DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
    
    # 构建提示词
    prompt = f"""
    请为今天的 GitHub Trending 每日推荐项目写一篇技术博客文章。

    项目信息：
    - 项目名称：{repo_data['name']}
    - 项目地址：{repo_data['url']}
    - 项目描述：{repo_data['desc']}
    - 推荐日期：{repo_data['date']}

    要求：
    1. 写一篇800-1200字的技术博客文章
    2. 文章标题要吸引人，包含项目名称
    3. 内容结构包括：
       - 项目介绍和背景
       - 主要功能特点
       - 技术栈分析（根据项目名推测）
       - 应用场景和价值
       - 总结和展望
    4. 使用专业但易懂的技术语言
    5. 包含适当的 HTML 标签（如 <p>, <h2>, <h3>, <code>, <strong> 等）
    6. 不要使用 Markdown，直接使用 HTML 格式
    7. 添加一些图标和表情符号以增加趣味性

    请直接返回文章内容，不需要额外的说明。
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
        "max_tokens": 2000
    }
    
    response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload)
    
    if response.status_code == 200:
        result = response.json()
        return result['choices'][0]['message']['content']
    else:
        print(f"DeepSeek API 错误: {response.status_code}")
        print(response.text)
        return None

def save_generated_post(content, repo_data):
    """保存生成的文章"""
    post_data = {
        "repo_info": repo_data,
        "generated_content": content,
        "generated_at": datetime.now().isoformat()
    }
    
    with open('generated_post.json', 'w', encoding='utf-8') as f:
        json.dump(post_data, f, ensure_ascii=False, indent=2)
    
    print("文章已生成并保存到 generated_post.json")

if __name__ == "__main__":
    # 读取仓库数据
    repo_data = read_repo_data()
    print(f"处理项目: {repo_data['name']}")
    
    # 生成文章
    post_content = generate_post_with_deepseek(repo_data)
    
    if post_content:
        # 保存生成的文章
        save_generated_post(post_content, repo_data)
        print("文章生成成功！")
    else:
        print("文章生成失败")
        exit(1)