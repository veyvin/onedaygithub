import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime

def get_trending_repo():
    url = "https://github.com/trending"
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"Failed to fetch GitHub Trending. Status code: {response.status_code}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    repo = soup.find("article", class_="Box-row")

    if not repo:
        print("No repository found.")
        return None

    repo_name = repo.h2.a.get_text(strip=True).replace("\n", "").replace(" ", "")
    repo_url = "https://github.com" + repo.h2.a["href"]
    description_tag = repo.p
    repo_desc = description_tag.get_text(strip=True) if description_tag else "No description"

    return {
        "name": repo_name,
        "url": repo_url,
        "desc": repo_desc,
        "date": datetime.now().strftime("%Y-%m-%d")
    }

def save_to_json(data, file_path="github_daily.json"):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Saved to {file_path}")

if __name__ == "__main__":
    repo_info = get_trending_repo()
    if repo_info:
        save_to_json(repo_info)
