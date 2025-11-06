import requests
from bs4 import BeautifulSoup
import json
import csv
import os
from datetime import datetime

CSV_FILE = "processed_repos.csv"

def load_processed_repos():
    """从 CSV 文件加载已处理的仓库列表"""
    processed = set()
    
    if not os.path.exists(CSV_FILE):
        print(f"CSV 文件不存在，将创建新文件: {CSV_FILE}")
        return processed
    
    try:
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 使用 URL 作为唯一标识（更可靠）
                repo_url = row.get('url', '').strip()
                if repo_url:
                    processed.add(repo_url)
        
        print(f"已加载 {len(processed)} 个已处理的仓库")
        return processed
    except Exception as e:
        print(f"读取 CSV 文件时出错: {e}")
        return processed

def save_processed_repo(repo_info):
    """将已处理的仓库保存到 CSV 文件"""
    file_exists = os.path.exists(CSV_FILE)
    
    try:
        with open(CSV_FILE, 'a', encoding='utf-8', newline='') as f:
            fieldnames = ['name', 'url', 'processed_date']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            # 如果文件不存在，写入表头
            if not file_exists:
                writer.writeheader()
            
            # 写入新记录
            writer.writerow({
                'name': repo_info['name'],
                'url': repo_info['url'],
                'processed_date': repo_info['date']
            })
        
        print(f"已保存到 CSV: {repo_info['name']} ({repo_info['url']})")
    except Exception as e:
        print(f"保存 CSV 文件时出错: {e}")

def get_trending_repos():
    """获取所有趋势仓库"""
    url = "https://github.com/trending"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            print(f"Failed to fetch GitHub Trending. Status code: {response.status_code}")
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
            # 保存到 CSV
            save_processed_repo(repo)
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