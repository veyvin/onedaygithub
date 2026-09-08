import requests
from bs4 import BeautifulSoup
import json
import csv
import os
import time
import traceback
from datetime import datetime

CSV_FILE = "processed_repos.csv"

# 抓取 GitHub Trending 的重试配置
MAX_RETRIES = 3
RETRY_DELAY = 2  # 秒


def load_processed_repos():
    """从 CSV 文件加载已处理的仓库列表"""
    processed = set()

    if not os.path.exists(CSV_FILE):
        print(f"CSV 文件不存在，将创建新文件: {CSV_FILE}")
        return processed

    # 检查文件是否为空
    if os.path.getsize(CSV_FILE) == 0:
        print(f"CSV 文件为空，将跳过读取")
        return processed

    try:
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            row_count = 0
            for row in reader:
                row_count += 1
                # 使用 URL 作为唯一标识（更可靠）
                repo_url = row.get('url', '').strip()
                if repo_url:
                    processed.add(repo_url)

            if row_count == 0:
                print(f"CSV 文件只包含表头，没有数据行")

        print(f"已加载 {len(processed)} 个已处理的仓库")
        return processed
    except Exception as e:
        print(f"读取 CSV 文件时出错: {e}")
        traceback.print_exc()
        return processed

def save_processed_repo(repo_info):
    """
    将已处理的仓库保存到 CSV 文件。
    返回 True 表示保存成功；False 表示失败（调用方不应继续后续流程，
    否则下次运行会因为 CSV 中没有该记录而重复发布文章）。
    """
    file_exists = os.path.exists(CSV_FILE)

    print(f"=== 保存仓库到 CSV ===")
    print(f"文件是否存在: {file_exists}")
    print(f"仓库信息: {repo_info}")

    try:
        # 使用追加模式打开文件
        with open(CSV_FILE, 'a', encoding='utf-8', newline='') as f:
            fieldnames = ['name', 'url', 'processed_date']
            writer = csv.DictWriter(f, fieldnames=fieldnames)

            # 如果文件不存在或为空，写入表头
            if not file_exists or os.path.getsize(CSV_FILE) == 0:
                print("写入 CSV 表头")
                writer.writeheader()

            # 写入新记录
            new_row = {
                'name': repo_info['name'],
                'url': repo_info['url'],
                'processed_date': repo_info['date']
            }
            writer.writerow(new_row)

            # 确保数据立即写入磁盘
            f.flush()
            os.fsync(f.fileno())

        print(f"已保存仓库记录: {repo_info['name']} ({repo_info['url']})")
        return True

    except Exception as e:
        print(f"保存 CSV 文件时出错: {e}")
        traceback.print_exc()
        return False


def _fetch_with_retry(url, headers, timeout=30, max_retries=MAX_RETRIES, delay=RETRY_DELAY):
    """带重试的 HTTP GET 请求，处理瞬时网络错误。返回 Response 或 None。"""
    last_response = None
    for attempt in range(max_retries):
        try:
            last_response = requests.get(url, headers=headers, timeout=timeout)
            if last_response.status_code == 200:
                return last_response
            print(f"请求失败，状态码: {last_response.status_code} (尝试 {attempt + 1}/{max_retries})")
        except requests.exceptions.RequestException as e:
            print(f"网络请求错误 (尝试 {attempt + 1}/{max_retries}): {e}")
            last_response = None
        if attempt < max_retries - 1:
            time.sleep(delay)
    return last_response


def get_trending_repos():
    """获取所有趋势仓库"""
    url = "https://github.com/trending"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        response = _fetch_with_retry(url, headers, timeout=30)
        if response is None or response.status_code != 200:
            print(f"Failed to fetch GitHub Trending after {MAX_RETRIES} retries")
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        repos = soup.find_all("article", class_="Box-row")

        if not repos:
            print("No repositories found.")
            return None

        repo_list = []
        for repo in repos:
            try:
                repo_name = repo.h2.a.get_text(strip=True).replace("\n", "").replace(" ", "")
                repo_url = "https://github.com" + repo.h2.a["href"]

                description_tag = repo.p
                repo_desc = description_tag.get_text(strip=True) if description_tag else "No description"

                # 获取星标数
                stars_tag = repo.find("a", href=lambda x: x and "stargazers" in x)
                stars = stars_tag.get_text(strip=True) if stars_tag else "N/A"

                repo_list.append({
                    "name": repo_name,
                    "url": repo_url,
                    "desc": repo_desc,
                    "stars": stars,
                    "date": datetime.now().strftime("%Y-%m-%d")
                })
            except Exception as e:
                print(f"解析仓库信息时出错: {e}")
                continue

        return repo_list

    except Exception as e:
        print(f"Error fetching trending repo: {e}")
        return None

def get_trending_repo():
    """获取第一个未处理过的趋势仓库"""
    processed_repos = load_processed_repos()
    repo_list = get_trending_repos()

    if not repo_list:
        return None

    # 遍历趋势列表，找到第一个未处理过的仓库
    for repo in repo_list:
        if repo['url'] not in processed_repos:
            print(f"找到未处理的仓库: {repo['name']} ({repo['url']})")
            # 保存到 CSV；保存失败则中止本次处理以避免重复发布
            if not save_processed_repo(repo):
                print(f"❌ 保存仓库到 CSV 失败，跳过本次处理以避免重复发布")
                return None
            return repo
        else:
            print(f"仓库已处理过，跳过: {repo['name']} ({repo['url']})")

    print("所有趋势仓库都已处理过")
    return None

def save_to_json(data, file_path="github_daily.json"):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Saved trending repo to {file_path}")

if __name__ == "__main__":
    repo_info = get_trending_repo()
    if repo_info:
        save_to_json(repo_info)
        print(f"今日推荐: {repo_info['name']}")
    else:
        print("未能获取 Trending 数据")
        exit(1)