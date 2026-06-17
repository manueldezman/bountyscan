import json
import os
import urllib.request
import urllib.parse
from datetime import datetime, timezone

# ─── Configuration ────────────────────────────────────────────────────────────
STATE_FILE = "seen_bounties.json"
MAX_COMMENTS = 25  # skip overcrowded / already-competitive threads

# ─── Search Queries ───────────────────────────────────────────────────────────
# Tuned for Web3 / hackathon / open-source bounty opportunities
SEARCH_QUERIES = [
    # Generic paid bounty issues
    'is:issue is:open bounty in:title,body sort:updated-desc',
    'is:issue is:open reward bounty sort:updated-desc',
    'is:issue is:open "paid" "PR" "bounty" sort:updated-desc',
    # Opire bounty platform
    'is:issue is:open "Opire" bounty sort:updated-desc',
    # Web3 / blockchain ecosystem grants & bounties
    'is:issue is:open "HBAR" bounty sort:updated-desc',
    'is:issue is:open "Hedera" bounty sort:updated-desc',
    'is:issue is:open "Celo" bounty sort:updated-desc',
    'is:issue is:open "Stacks" bounty sort:updated-desc',
    'is:issue is:open "Base" bounty sort:updated-desc',
    'is:issue is:open "Mantle" bounty sort:updated-desc',
    'is:issue is:open hackathon prize "TypeScript" sort:updated-desc',
    'is:issue is:open "LangChain" OR "LangGraph" bounty sort:updated-desc',
    'is:issue is:open grant "open source" "good first issue" sort:updated-desc',
]

# ─── Spam / noise blocklist ───────────────────────────────────────────────────
BLOCKLIST = [
    "airdrop", "referral", "casino", "gambling", "trading bot",
    "blog post", "article writing", "tutorial proposal", "content creator",
    "phishing", "spam", "scam",
]

# ─── Repo blocklist (farming repos, self-repo) ────────────────────────────────
REPO_BLOCKLIST = [
    "SecureBananaLabs/bug-bounty",  # farming repo — bulk fake issues
    "greyw0rks/bountyscout",        # self — bot's own alert issues
]


def load_seen_bounties() -> set:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
        except Exception as e:
            print(f"[WARN] Could not load state file: {e}")
    return set()


def save_seen_bounties(seen_urls: set):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(seen_urls)), f, indent=2)
    except Exception as e:
        print(f"[ERROR] Could not save state file: {e}")


def search_github(query: str, token: str | None) -> dict:
    params = urllib.parse.urlencode({"q": query, "per_page": 15})
    url = f"https://api.github.com/search/issues?{params}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "greyw0rks-BountyScout",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[ERROR] GitHub API failed for query '{query[:60]}': {e}")
        return {}


def is_clean_candidate(item: dict) -> bool:
    # Skip pull requests
    if "pull_request" in item:
        return False
    # Skip already assigned issues
    if item.get("assignees"):
        return False
    # Skip overcrowded threads
    if int(item.get("comments", 0)) > MAX_COMMENTS:
        return False

    # Skip blocked repos (farming accounts, self-repo)
    repo = item.get("repository_url", "").replace("https://api.github.com/repos/", "")
    if any(repo.lower() == blocked.lower() for blocked in REPO_BLOCKLIST):
        return False

    title = str(item.get("title", "")).lower()
    body = str(item.get("body", "") or "").lower()

    if any(term in title or term in body for term in BLOCKLIST):
        return False

    return True


# ─── Notification senders ─────────────────────────────────────────────────────

def send_telegram(token: str, chat_id: str, message: str):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            print("[OK] Telegram notification sent.")
    except Exception as e:
        print(f"[ERROR] Telegram failed: {e}")


def send_discord(webhook_url: str, message: str):
    payload = {"content": message}
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            print("[OK] Discord notification sent.")
    except Exception as e:
        print(f"[ERROR] Discord failed: {e}")


def create_github_issue(repo: str, token: str, title: str, body: str):
    url = f"https://api.github.com/repos/{repo}/issues"
    payload = {"title": title, "body": body, "labels": ["bounty-alert"]}
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "greyw0rks-BountyScout",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            print("[OK] GitHub Issue notification created.")
    except Exception as e:
        print(f"[ERROR] GitHub Issue creation failed: {e}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    github_token    = os.environ.get("GITHUB_TOKEN")
    repo_fullname   = os.environ.get("GITHUB_REPOSITORY")      # e.g. greyw0rks/BountyScout
    telegram_token  = os.environ.get("TELEGRAM_BOT_TOKEN")
    telegram_chat   = os.environ.get("TELEGRAM_CHAT_ID")
    discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL")

    seen_urls = load_seen_bounties()
    new_bounties: list[dict] = []

    print("🔍 Scouting GitHub for active bounties...")
    for query in SEARCH_QUERIES:
        results = search_github(query, github_token)
        for item in results.get("items", []):
            url = item.get("html_url")
            if url and url not in seen_urls and is_clean_candidate(item):
                new_bounties.append({
                    "title":      item.get("title"),
                    "url":        url,
                    "repo":       url.split("/issues/")[0].replace("https://github.com/", ""),
                    "comments":   item.get("comments", 0),
                    "updated_at": item.get("updated_at"),
                })
                seen_urls.add(url)

    if not new_bounties:
        print("✅ No new bounties found this run.")
        return

    count = len(new_bounties)
    print(f"🎯 Discovered {count} NEW bounty opportunit{'ies' if count != 1 else 'y'}!")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    plural  = "ies" if count != 1 else "y"

    # ── Telegram / Discord message (Markdown) ────────────────────────────────
    lines = [
        f"🎯 *Bounty Alert* — {now_str}",
        f"Found *{count}* new opportunit{plural}:\n",
    ]
    for i, b in enumerate(new_bounties, 1):
        lines += [
            f"{i}. *{b['title']}*",
            f"   • Repo: `{b['repo']}`",
            f"   • Comments: {b['comments']}",
            f"   • Link: {b['url']}\n",
        ]
    notif_msg = "\n".join(lines)

    if telegram_token and telegram_chat:
        send_telegram(telegram_token, telegram_chat, notif_msg)

    if discord_webhook:
        send_discord(discord_webhook, notif_msg.replace("•", "-"))

    # ── GitHub Issue (zero-config, uses built-in GITHUB_TOKEN) ───────────────
    if github_token and repo_fullname:
        issue_title = f"🎯 Bounty Alert: {count} New Opportunit{plural} — {now_str}"
        issue_body  = f"### Bounty Scan Results\n\n**Scan Time:** {now_str}\n\n"
        for i, b in enumerate(new_bounties, 1):
            issue_body += (
                f"#### {i}. [{b['title']}]({b['url']})\n"
                f"- **Repo:** [{b['repo']}](https://github.com/{b['repo']})\n"
                f"- **Comments:** {b['comments']}\n"
                f"- **Last Updated:** {b['updated_at']}\n\n"
            )
        create_github_issue(repo_fullname, github_token, issue_title, issue_body)

    save_seen_bounties(seen_urls)
    print("💾 State saved.")


if __name__ == "__main__":
    main()
