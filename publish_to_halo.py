import json
import requests
import os
from datetime import datetime

def read_generated_post():
    """读取生成的文章"""
    with open('generated_post.json', 'r', encoding='utf-8') as f:
        return json.load(f)

def publish_to_halo(post_data):
    """发布文章到 Halo"""
    
    # Halo 配置
    HALO_URL = "https://veyvin.com"
    HALO_TOKEN = os.getenv('HALO_TOKEN')
    
    repo_info = post_data['repo_info']
    content = post_data['generated_content']
    
    # 从内容中提取标题（取第一行作为标题）
    lines = content.strip().split('\n')
    title = lines[0].replace('<h1>', '').replace('</h1>', '').strip()
    if not title or len(title) > 100:
        title = f"GitHub Trending 推荐：{repo_info['name']}"
    
    # 生成 slug
    slug = f"github-trending-{repo_info['date']}"
    
    headers = {
        "Authorization": f"Bearer {HALO_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "post": {
            "spec": {
                "title": title,
                "slug": slug,
                "template": "",
                "cover": "",
                "deleted": False,
                "publish": True,
                "publishTime": f"{repo_info['date']}T08:00:00Z",
                "pinned": False,
                "allowComment": True,
                "visible": "PUBLIC",
                "priority": 0,
                "excerpt": {
                    "autoGenerate": True,
                    "raw": repo_info['desc'][:100] + "..."
                },
                "categories": ["github-trending"],
                "tags": ["GitHub", "Trending", "开源项目"],
                "htmlMetas": []
            },
            "apiVersion": "content.halo.run/v1alpha1",
            "kind": "Post",
            "metadata": {
                "name": slug,
                "generateName": "post-"
            }
        },
        "content": {
            "raw": content,
            "content": content,
            "rawType": "HTML"
        }
    }
    
    response = requests.post(
        f"{HALO_URL}/apis/api.console.halo.run/v1alpha1/posts",
        headers=headers,
        json=payload
    )
    
    if response.status_code == 200:
        print("文章发布到 Halo 成功！")
        return response.json()
    else:
        print(f"发布失败: {response.status_code}")
        print(response.text)
        return None

if __name__ == "__main__":
    # 读取生成的文章
    post_data = read_generated_post()
    
    # 发布到 Halo
    result = publish_to_halo(post_data)
    
    if result:
        print("自动化流程完成！")
    else:
        print("发布失败")
        exit(1)