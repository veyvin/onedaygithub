import json
import requests
import os
from datetime import datetime, timedelta

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

def get_beijing_time(date_str):
    """将 GitHub 的 UTC 日期转换为北京时间"""
    # GitHub 的日期是 UTC 时间，转换为北京时间 (UTC+8)
    utc_date = datetime.strptime(date_str, "%Y-%m-%d")
    beijing_date = utc_date + timedelta(hours=8)
    return beijing_date

def get_previous_day_beijing(date_str):
    """获取前一天的北京时间"""
    beijing_time = get_beijing_time(date_str)
    previous_date = beijing_time - timedelta(days=1)
    return previous_date

def publish_to_halo(post_data):
    """发布文章到 Halo"""
    
    # Halo 配置
    HALO_URL = "https://veyvin.com"
    HALO_TOKEN = os.getenv('HALO_TOKEN')
    
    if not HALO_TOKEN:
        print("错误: 未找到 HALO_TOKEN 环境变量")
        return None
    
    repo_info = post_data['repo_info']
    title = post_data['title']
    content = post_data['content']
    
    # 获取前一天的北京时间
    previous_date_obj = get_previous_day_beijing(repo_info['date'])
    previous_date_str = previous_date_obj.strftime("%Y-%m-%d")
    
    # 生成 slug - 使用前一天的日期
    slug = f"github-trending-{previous_date_str}"
    
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
                # 修改：使用前一天的北京时间（早上8点）
                "publishTime": f"{previous_date_str}T08:00:00+08:00",
                "pinned": False,
                "allowComment": True,
                "visible": "PUBLIC",
                "priority": 0,
                "excerpt": {
                    "autoGenerate": False,
                    "raw": repo_info['desc'][:150]
                },
                "categories": ["github-trending"],
                # 修改：添加指定的标签
                "tags": ["GitHub", "Trending", "开源项目", "每日推荐", "自动发布文章", "自动化"],
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
            print(f"GitHub 原始日期: {repo_info['date']}")
            print(f"发布时间 (北京时间): {previous_date_str}T08:00:00+08:00")
            print(f"文章标签: GitHub, Trending, 开源项目, 每日推荐, 自动发布文章, 自动化")
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
        print(f"文章已设置为前一天发布，包含指定的自动化标签")
    else:
        print("发布失败")
        exit(1)