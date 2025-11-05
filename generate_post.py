import json
import requests
import os
from datetime import datetime

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

def generate_post_with_deepseek(repo_data):
    """使用 DeepSeek API 生成博客文章"""
    
    # 从环境变量获取 API 密钥
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
    
    if not DEEPSEEK_API_KEY:
        print("错误: 未找到 DEEPSEEK_API_KEY 环境变量")
        print("请在 GitHub Secrets 中设置 DEEPSEEK_API_KEY")
        return None
    
    print(f"API Key 前几位: {DEEPSEEK_API_KEY[:10]}...")  # 调试信息
    
    DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
    
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
        "max_tokens": 4000,
        "stream": False
    }
    
    try:
        print("正在调用 DeepSeek API...")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        print(f"API 响应状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
        else:
            print(f"DeepSeek API 错误: {response.status_code}")
            print(f"错误详情: {response.text}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"网络请求错误: {e}")
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
    if not repo_data:
        print("无法读取仓库数据，退出")
        exit(1)
        
    print(f"处理项目: {repo_data['name']}")
    
    # 生成文章
    post_content = generate_post_with_deepseek(repo_data)
    
    if post_content:
        # 保存生成的文章
        save_generated_post(post_content, repo_data)
        print("文章生成成功！")
        print(f"文章长度: {len(post_content)} 字符")
    else:
        print("文章生成失败")
        exit(1)