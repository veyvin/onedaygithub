import json
import requests
import os
from datetime import datetime, timedelta
import re

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

def generate_unique_slug(repo_name, date_str):
    """生成唯一的 slug，使用项目名称作为后缀"""
    # 获取当前的北京时间
    beijing_date_obj = get_beijing_time(date_str)
    beijing_date_str = beijing_date_obj.strftime("%Y-%m-%d")
    
    # 处理项目名称，生成安全的 slug 部分
    repo_name_slug = repo_name.replace('/', '-').replace(' ', '-').lower()
    # 移除特殊字符，只保留字母、数字、连字符和下划线
    repo_name_slug = re.sub(r'[^a-z0-9\-_]', '', repo_name_slug)
    
    # 如果项目名称部分太长，截断
    if len(repo_name_slug) > 30:
        repo_name_slug = repo_name_slug[:30]
    
    # 组合成完整的 slug
    slug = f"github-trending-{beijing_date_str}-{repo_name_slug}"
    
    # 确保总长度不超过限制
    if len(slug) > 60:
        # 如果还是太长，进一步截断项目名称部分
        max_repo_length = 60 - len(f"github-trending-{beijing_date_str}-") - 1
        repo_name_slug = repo_name_slug[:max_repo_length]
        slug = f"github-trending-{beijing_date_str}-{repo_name_slug}"
    
    return slug, beijing_date_str

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
    
    # 生成唯一的 slug
    slug, previous_date_str = generate_unique_slug(repo_info['name'], repo_info['date'])
    
    print(f"生成的唯一 slug: {slug}")
    print(f"发布日期: {previous_date_str}")
    
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
                # 使用当前的北京时间（早上8点）
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
                # 添加指定的标签
                "tags": ["GitHub", "Trending", "开源项目", "每日推荐", "自动发布文章", "自动化"],
                "htmlMetas": []
            },
            "apiVersion": "content.halo.run/v1alpha1",
            "kind": "Post",
            "metadata": {
                "name": slug,  # 使用相同的 slug 作为名称
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
            print("✅ 文章发布到 Halo 成功！")
            print(f"📝 文章标题: {title}")
            print(f"🔗 文章 slug: {slug}")
            print(f"📅 GitHub 原始日期: {repo_info['date']}")
            print(f"🕗 发布时间 (北京时间): {previous_date_str}T08:00:00+08:00")
            print(f"🏷️ 文章标签: GitHub, Trending, 开源项目, 每日推荐, 自动发布文章, 自动化")
            print(f"📂 项目名称: {repo_info['name']}")
            return response.json()
        else:
            print(f"❌ 发布失败: {response.status_code}")
            print(f"📋 错误详情: {response.text}")
            
            # 如果是重复错误，提供更详细的解决方案
            if response.status_code == 400 and "名称重复" in response.text:
                print("\n💡 解决方案:")
                print("   虽然使用了唯一 slug，但仍然出现重复，可能是极端情况")
                print("   建议检查 Halo 后台是否已存在相同标题或 slug 的文章")
                print(f"   当前 slug: {slug}")
            
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"🌐 发布请求错误: {e}")
        return None

if __name__ == "__main__":
    # 读取生成的文章
    post_data = read_generated_post()
    if not post_data:
        print("无法读取生成的文章数据")
        exit(1)
    
    print(f"开始发布文章到 Halo...")
    print(f"项目: {post_data['repo_info']['name']}")
    print(f"标题: {post_data['title']}")
    
    # 发布到 Halo
    result = publish_to_halo(post_data)
    
    if result:
        print("\n🎉 自动化流程完成！文章已成功发布到 Halo")
        print("✅ 文章已设置为当天发布")
        print("✅ 包含指定的自动化标签")
        print("✅ 使用唯一 slug 避免重复")
    else:
        print("\n❌ 发布失败")
        exit(1)