import json
import requests
import os
from datetime import datetime

def read_generated_post():
    """读取生成的文章"""
    try:
        with open('generated_post.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("generated_post.json 文件不存在")
        return None
    except json.JSONDecodeError:
        print("generated_post.json 文件格式错误")
        return None

def publish_to_halo(post_data):
    """发布文章到 Halo"""
    
    # Halo 配置
    HALO_URL = "http://veyvin.com"
    HALO_TOKEN = os.getenv('HALO_TOKEN')
    
    if not HALO_TOKEN:
        print("错误: 未找到 HALO_TOKEN 环境变量")
        return None
    
    repo_info = post_data['repo_info']
    title = post_data['title']
    content = post_data['content']
    
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
                    "autoGenerate": False,
                    "raw": repo_info['desc'][:150]
                },
                "categories": ["github-trending"],
                "tags": ["GitHub", "Trending", "开源项目", "每日推荐"],
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
    
    try:
        response = requests.post(
            f"{HALO_URL}/apis/api.console.halo.run/v1alpha1/posts",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            print("文章发布到 Halo 成功！")
            return response.json()
        else:
            print(f"发布失败: {response.status_code}")
            print(f"错误详情: {response.text}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"发布请求错误: {e}")
        return None

if __name__ == "__main__":
    # 读取生成的文章
    post_data = read_generated_post()
    if not post_data:
        print("无法读取生成的文章数据")
        exit(1)
    
    # 发布到 Halo
    result = publish_to_halo(post_data)
    
    if result:
        print("自动化流程完成！文章已发布到 Halo")
    else:
        print("发布失败")
        exit(1)