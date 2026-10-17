import requests
from bs4 import BeautifulSoup
import json
import csv
import os
import re
import time
import traceback
from datetime import datetime

CSV_FILE = "processed_repos.csv"

# 抓取 GitHub Trending 的重试配置
MAX_RETRIES = 3
RETRY_DELAY = 2  # 秒

# Trending 抓取源，按优先级从高到低排列。
#
# GitHub 官方 Trending 页面没有「国家/地区」筛选，但保留了 spoken_language_code
# 参数（按项目描述语言筛选）。国内项目绝大多数是中文描述，因此
# spoken_language_code=zh 基本等价于「中国区趋势」。
#
# 每天的榜单只有十几个条目，被抓完是常态（表现为「所有趋势仓库都已处理过」）。
# 因此按顺序遍历多个来源，取第一个还有未处理仓库的来源，
# 既保证内容新鲜度（全球日榜每天都有新项目），也保证不会轻易「断更」。
TRENDING_SOURCES = [
    {
        "id": "global-daily",
        "label": "GitHub 全球日榜",
        "period": "daily",
        "url": "https://github.com/trending?since=daily",
    },
    {
        "id": "zh-daily",
        "label": "中文区日榜（中国）",
        "period": "daily",
        "url": "https://github.com/trending?since=daily&spoken_language_code=zh",
    },
    {
        "id": "zh-weekly",
        "label": "中文区周榜（中国）",
        "period": "weekly",
        "url": "https://github.com/trending?since=weekly&spoken_language_code=zh",
    },
    {
        "id": "en-daily",
        "label": "英文区日榜",
        "period": "daily",
        "url": "https://github.com/trending?since=daily&spoken_language_code=en",
    },
    {
        "id": "global-weekly",
        "label": "GitHub 全球周榜",
        "period": "weekly",
        "url": "https://github.com/trending?since=weekly",
    },
    {
        "id": "ja-daily",
        "label": "日文区日榜",
        "period": "daily",
        "url": "https://github.com/trending?since=daily&spoken_language_code=ja",
    },
    {
        "id": "de-daily",
        "label": "德文区日榜",
        "period": "daily",
        "url": "https://github.com/trending?since=daily&spoken_language_code=de",
    },
    {
        "id": "es-daily",
        "label": "西文区日榜",
        "period": "daily",
        "url": "https://github.com/trending?since=daily&spoken_language_code=es",
    },
]

DEFAULT_SOURCE = TRENDING_SOURCES[0]


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


def _extract_repo_language(repo):
    """从 trending 页面条目中提取项目主语言。"""
    lang_tag = repo.find("span", itemprop="programmingLanguage")
    if lang_tag:
        return lang_tag.get_text(strip=True)
    return "N/A"


_STARS_PERIOD_RE = re.compile(r"([\d,]+)\s+stars?\s+(today|this week|this month)", re.IGNORECASE)


def _extract_today_stars(repo):
    """从 trending 页面条目中提取区间内新增的 star 数。

    GitHub 改版后不再使用 `d-inline-none float-sm-right` 这个 class，
    改为 `span.d-inline-block` 里的纯文本（如 "1,552 stars today"），
    因此这里先按旧 class 找，找不到再按文本兜底匹配。
    """
    today_tag = repo.find("span", class_="d-inline-none float-sm-right")
    if today_tag:
        return today_tag.get_text(strip=True)

    for tag in repo.find_all("span", class_="d-inline-block"):
        text = tag.get_text(" ", strip=True)
        if _STARS_PERIOD_RE.search(text):
            return text

    for text in repo.find_all(string=True):
        match = _STARS_PERIOD_RE.search(str(text))
        if match:
            return match.group(0)
    return "N/A"


def get_trending_repos(source=None):
    """获取某个来源的趋势仓库列表。

    source 可以是 TRENDING_SOURCES 中的一项、包含 url 的字典，或直接的 URL 字符串；
    省略时使用优先级最高的全球日榜。
    """
    if source is None:
        source = DEFAULT_SOURCE
    if isinstance(source, str):
        source = {"id": "custom", "label": source, "period": "daily", "url": source}

    url = source["url"]
    source_id = source.get("id", "custom")
    source_label = source.get("label", url)
    period = source.get("period", "daily")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        response = _fetch_with_retry(url, headers, timeout=30)
        if response is None or response.status_code != 200:
            print(f"Failed to fetch {source_label} after {MAX_RETRIES} retries")
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        repos = soup.find_all("article", class_="Box-row")

        if not repos:
            print(f"{source_label}: No repositories found.")
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
                    "language": _extract_repo_language(repo),
                    "today_stars": _extract_today_stars(repo),
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "source": source_id,
                    "source_label": source_label,
                    "period": period
                })
            except Exception as e:
                print(f"解析仓库信息时出错: {e}")
                continue

        return repo_list

    except Exception as e:
        print(f"Error fetching trending repo from {source_label}: {e}")
        return None


def _pick_unprocessed(repo_list, processed_repos):
    """返回列表中第一个未处理的仓库；全部处理过则返回 None。"""
    for repo in repo_list:
        if repo['url'] not in processed_repos:
            return repo
        print(f"仓库已处理过，跳过: {repo['name']} ({repo['url']})")
    return None


def get_trending_repo():
    """获取第一个未处理过的趋势仓库。

    按 TRENDING_SOURCES 的顺序遍历来源：某个来源的榜单被处理完后自动降级到下一个
    （例如全球日榜抓完 → 中文区日榜 → 中文区周榜 → 其他语言区）。

    设置环境变量 GITHUB_TRENDING_SOURCE=<来源 id> 可强制只使用指定来源，
    例如 GITHUB_TRENDING_SOURCE=zh-daily 强制只发中国区趋势。
    """
    processed_repos = load_processed_repos()
    sources = TRENDING_SOURCES

    forced = os.getenv("GITHUB_TRENDING_SOURCE", "").strip()
    if forced:
        selected = [s for s in TRENDING_SOURCES if s["id"] == forced]
        if not selected:
            valid = ", ".join(s["id"] for s in TRENDING_SOURCES)
            print(f"❌ 未知的来源 id: {forced}（可选: {valid}）")
            return None
        sources = selected
        print(f"=== 已指定来源，仅使用: {selected[0]['label']} ===")

    exhausted = []

    for index, source in enumerate(sources):
        label = source.get("label", source.get("id", source.get("url")))

        print(f"=== 尝试来源 {index + 1}/{len(sources)}: {label} ===")
        repo_list = get_trending_repos(source)

        if not repo_list:
            print(f"{label}: 未获取到数据")
            continue

        repo = _pick_unprocessed(repo_list, processed_repos)
        if repo is None:
            exhausted.append(label)
            print(f"{label}: 榜单内 {len(repo_list)} 个仓库均已处理过，降级到下一个来源")
            continue

        print(f"找到未处理的仓库: {repo['name']} ({repo['url']}) [来源: {label}]")
        # 保存到 CSV；保存失败则中止本次处理以避免重复发布
        if not save_processed_repo(repo):
            print(f"❌ 保存仓库到 CSV 失败，跳过本次处理以避免重复发布")
            return None
        return repo

    if exhausted:
        print(f"已耗尽的来源: {', '.join(exhausted)}")
    print("所有趋势来源都已处理过")
    return None

def save_to_json(data, file_path="github_daily.json"):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Saved trending repo to {file_path}")

if __name__ == "__main__":
    repo_info = get_trending_repo()
    if repo_info:
        save_to_json(repo_info)
        print(f"今日推荐: {repo_info['name']}（来源: {repo_info.get('source_label', '未知')}）")
    else:
        # 所有来源都取不到新仓库时必须非零退出：否则 workflow 会继续用 checkout
        # 里的旧 github_daily.json 跑发布，导致重复发文。
        print("未能获取 Trending 数据")
        exit(1)
