import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime

def get_trending_repo():
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

        # 获取第一个仓库
        repo = repos[0]
        repo_name = repo.h2.a.get_text(strip=True).replace("\n", "").replace(" ", "")
        repo_url = "https://github.com" + repo.h2.a["href"]
        
        description_tag = repo.p
        repo_desc = description_tag.get_text(strip=True) if description_tag else "No description"

        # 获取星标数
        stars_tag = repo.find("a", href=lambda x: x and "stargazers" in x)
        stars = stars_tag.get_text(strip=True) if stars_tag else "N/A"

        return {
            "name": repo_name,
            "url": repo_url,
            "desc": repo_desc,
            "stars": stars,
            "date": datetime.now().strftime("%Y-%m-%d")
        }
        
    except Exception as e:
        print(f"Error fetching trending repo: {e}")
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