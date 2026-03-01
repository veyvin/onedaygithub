import json
import os
import re
import requests
import time
from datetime import datetime, timedelta

# 默认分类和标签（可被 post_data 中的 categories/tags 覆盖）
DEFAULT_CATEGORIES = ["GitHub Trending", "开源项目"]
DEFAULT_TAGS = ["GitHub", "Trending", "开源项目", "每日推荐", "自动发布", "自动化"]


def retry_request(max_retries=3, delay=2):
    """网络请求重试装饰器，处理临时失败"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    result = func(*args, **kwargs)
                    return result
                except requests.exceptions.RequestException as e:
                    retries += 1
                    if retries >= max_retries:
                        raise
                    print(f"  网络请求失败，{delay}秒后重试 ({retries}/{max_retries}): {e}")
                    time.sleep(delay)
        return wrapper
    return decorator


def _to_ascii_slug(s: str) -> str:
    """生成 ASCII 安全 slug，用于 metadata.name"""
    s = re.sub(r"[^a-z0-9\-_\u4e00-\u9fa5]", "-", s.lower())
    s = re.sub(r"-+", "-", s).strip("-")
    if not s or not s[0].isascii():
        s = "cat-" + (s or "default")[:50]
    return (s or "default")[:63]


@retry_request(max_retries=3, delay=3)
def list_categories(halo_url: str, headers: dict) -> list:
    """获取分类列表"""
    url = f"{halo_url.rstrip('/')}/apis/content.halo.run/v1alpha1/categories"
    r = requests.get(url, headers=headers, params={"size": 100}, timeout=15)
    if r.status_code != 200:
        return []
    data = r.json()
    return data.get("items") or []


@retry_request(max_retries=3, delay=3)
def list_tags(halo_url: str, headers: dict) -> list:
    """获取标签列表"""
    url = f"{halo_url.rstrip('/')}/apis/content.halo.run/v1alpha1/tags"
    r = requests.get(url, headers=headers, params={"size": 100}, timeout=15)
    if r.status_code != 200:
        return []
    data = r.json()
    return data.get("items") or []


@retry_request(max_retries=3, delay=3)
def create_category(halo_url: str, headers: dict, display_name: str, slug: str) -> str | None:
    """创建分类，返回 metadata.name"""
    url = f"{halo_url.rstrip('/')}/apis/content.halo.run/v1alpha1/categories"
    name = _to_ascii_slug(slug)
    payload = {
        "apiVersion": "content.halo.run/v1alpha1",
        "kind": "Category",
        "metadata": {"name": name},
        "spec": {
            "displayName": display_name,
            "slug": slug or name,
            "description": "",
            "cover": "",
            "template": "",
            "priority": 0,
            "children": [],
        },
    }
    r = requests.post(url, headers=headers, json=payload, timeout=15)
    if r.status_code not in (200, 201):
        print(f"   创建分类失败 [{display_name}]: {r.status_code} - {r.text[:150]}")
        return None
    data = r.json()
    return data.get("metadata", {}).get("name")


@retry_request(max_retries=3, delay=3)
def create_tag(halo_url: str, headers: dict, display_name: str, slug: str) -> str | None:
    """创建标签，返回 metadata.name"""
    url = f"{halo_url.rstrip('/')}/apis/content.halo.run/v1alpha1/tags"
    name = _to_ascii_slug(slug)
    payload = {
        "apiVersion": "content.halo.run/v1alpha1",
        "kind": "Tag",
        "metadata": {"name": name},
        "spec": {"displayName": display_name, "slug": slug or name},
    }
    r = requests.post(url, headers=headers, json=payload, timeout=15)
    if r.status_code not in (200, 201):
        print(f"   创建标签失败 [{display_name}]: {r.status_code} - {r.text[:150]}")
        return None
    data = r.json()
    return data.get("metadata", {}).get("name")


def ensure_category(halo_url: str, headers: dict, display_name: str) -> str | None:
    """确保分类存在，返回 metadata.name。不存在则创建"""
    slug = re.sub(r"[^a-z0-9\-_\u4e00-\u9fa5]", "-", display_name.lower())
    slug = re.sub(r"-+", "-", slug).strip("-") or "default"
    cats = list_categories(halo_url, headers)
    
    # 详细检查分类是否存在
    for c in cats:
        s = c.get("spec", {})
        if s.get("displayName") == display_name:
            return c.get("metadata", {}).get("name")
        if s.get("slug") == slug:
            return c.get("metadata", {}).get("name")
    
    # 分类不存在，创建新分类
    created = create_category(halo_url, headers, display_name, slug)
    if created:
        return created
    
    # 创建失败，返回第一个分类作为 fallback
    if cats:
        return cats[0].get("metadata", {}).get("name")
    return None


def ensure_tag(halo_url: str, headers: dict, display_name: str) -> str | None:
    """确保标签存在，返回 metadata.name。不存在则创建"""
    slug = re.sub(r"[^a-z0-9\-_\u4e00-\u9fa5]", "-", display_name.lower())
    slug = re.sub(r"-+", "-", slug).strip("-") or "default"
    tags_list = list_tags(halo_url, headers)
    
    # 详细检查标签是否存在
    for t in tags_list:
        s = t.get("spec", {})
        if s.get("displayName") == display_name:
            return t.get("metadata", {}).get("name")
        if s.get("slug") == slug:
            return t.get("metadata", {}).get("name")
    
    # 标签不存在，创建新标签
    created = create_tag(halo_url, headers, display_name, slug)
    if created:
        return created
    
    # 创建失败，返回第一个标签作为 fallback
    if tags_list:
        return tags_list[0].get("metadata", {}).get("name")
    return None


def resolve_categories_and_tags(
    halo_url: str,
    headers: dict,
    category_names: list[str],
    tag_names: list[str],
) -> tuple[list[str], list[str]]:
    """
    将分类、标签的显示名解析为 metadata.name（ID）。
    不存在则自动创建。若都为空，则使用已有分类/标签作为 fallback。
    """
    # 去重处理，避免重复创建相同的分类和标签
    unique_category_names = []
    seen_categories = set()
    for c in (category_names or []):
        c_str = str(c).strip()
        if c_str and c_str not in seen_categories:
            unique_category_names.append(c_str)
            seen_categories.add(c_str)
    
    unique_tag_names = []
    seen_tags = set()
    for t in (tag_names or []):
        t_str = str(t).strip()
        if t_str and t_str not in seen_tags:
            unique_tag_names.append(t_str)
            seen_tags.add(t_str)
    
    # 解析分类和标签
    cat_ids = [ensure_category(halo_url, headers, c) for c in unique_category_names]
    tag_ids = [ensure_tag(halo_url, headers, t) for t in unique_tag_names]
    
    # 过滤无效 ID
    cat_ids = [x for x in cat_ids if x]
    tag_ids = [x for x in tag_ids if x]

    # 如果没有分类或标签，使用已有数据作为 fallback
    cats = list_categories(halo_url, headers)
    tags_list = list_tags(halo_url, headers)
    if not cat_ids and cats:
        cat_ids = [c.get("metadata", {}).get("name") for c in cats if c.get("metadata", {}).get("name")]
    if not tag_ids and tags_list:
        tag_ids = [t.get("metadata", {}).get("name") for t in tags_list if t.get("metadata", {}).get("name")]

    return cat_ids, tag_ids


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

@retry_request(max_retries=3, delay=5)
def publish_to_halo(post_data):
    """发布文章到 Halo"""
    
    # Halo 配置（支持环境变量覆盖）
    HALO_URL = (os.getenv("HALO_URL") or "https://veyvin.com").rstrip("/")
    HALO_TOKEN = os.getenv('HALO_TOKEN')
    
    if not HALO_TOKEN:
        print("错误: 未找到 HALO_TOKEN 环境变量")
        return None

    repo_info = post_data.get("repo_info") or {}
    if not repo_info.get("name") or not repo_info.get("date"):
        print("错误: post_data 缺少 repo_info.name 或 repo_info.date")
        return None
    title = post_data.get("title") or ""
    content = post_data.get("content") or ""
    if not title or not content:
        print("错误: post_data 缺少 title 或 content")
        return None

    # 从 post_data 读取分类和标签，若无或类型错误则使用默认值
    raw_cats = post_data.get("categories")
    raw_tags = post_data.get("tags")
    category_names = raw_cats if isinstance(raw_cats, list) else DEFAULT_CATEGORIES
    tag_names = raw_tags if isinstance(raw_tags, list) else DEFAULT_TAGS

    # 生成唯一的 slug
    slug, previous_date_str = generate_unique_slug(repo_info['name'], repo_info['date'])

    print(f"生成的唯一 slug: {slug}")
    print(f"发布日期: {previous_date_str}")

    headers = {
        "Authorization": f"Bearer {HALO_TOKEN}",
        "Content-Type": "application/json"
    }

    # 解析分类和标签为 Halo 的 metadata.name（ID），不存在则创建
    print("准备分类和标签...")
    cat_ids, tag_ids = resolve_categories_and_tags(
        HALO_URL, headers, category_names, tag_names
    )
    print(f"  分类: {category_names} -> {cat_ids}")
    print(f"  标签: {tag_names[:5]}{'...' if len(tag_names) > 5 else ''} -> {tag_ids[:5]}{'...' if len(tag_ids) > 5 else ''}")

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
                    "raw": (repo_info.get("desc") or "")[:150]
                },
                "categories": cat_ids,
                "tags": tag_ids,
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
            print(f"🏷️ 文章分类: {category_names}")
            print(f"🏷️ 文章标签: {tag_names}")
            print(f"📂 项目名称: {repo_info['name']}")
            return response.json()
        elif response.status_code == 530:
            # Cloudflare 530 错误，通常是临时网络问题
            print(f"🌐 Cloudflare 530 错误: {response.text[:200]}")
            print("💡 提示: 这通常是临时的网络连接问题，重试可能会解决")
            raise requests.exceptions.RequestException("Cloudflare 530 Tunnel error")
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
        raise

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