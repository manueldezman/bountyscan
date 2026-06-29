import json
import os
import re
import time
import urllib.error
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

# ─── Configuration ────────────────────────────────────────────────────────────
STATE_FILE = "seen_bounties.json"
MAX_COMMENTS = 5  # skip overcrowded / already-competitive threads
MAX_LINKED_PRS = 1
RECENT_WINDOW_HOURS = 1
TELEGRAM_MESSAGE_LIMIT = 3500

# ─── Search Queries ───────────────────────────────────────────────────────────
# Tuned for Web3 / hackathon / open-source bounty opportunities
SEARCH_QUERIES = [
    # Generic explicit-paid bounty issues
    'is:issue is:open bounty reward sort:updated-desc',
    'is:issue is:open bounty paid sort:updated-desc',
    'is:issue is:open bounty prize sort:updated-desc',
    'is:issue is:open bounty grant sort:updated-desc',
    'is:issue is:open bounty payout sort:updated-desc',
    'is:issue is:open bounty payment sort:updated-desc',
    'is:issue is:open "paid issue" sort:updated-desc',
    'is:issue is:open "up for grabs" reward sort:updated-desc',
    'is:issue is:open reward "$" sort:updated-desc',
    'is:issue is:open reward usdc sort:updated-desc',
    'is:issue is:open reward eth sort:updated-desc',
    # Platform / ecosystem paid work patterns
    'is:issue is:open "Opire" reward sort:updated-desc',
    'is:issue is:open "gitcoin" grant sort:updated-desc',
    'is:issue is:open "superfluid" bounty reward sort:updated-desc',
    'is:issue is:open "dework" task reward sort:updated-desc',
    'is:issue is:open hackathon prize "TypeScript" sort:updated-desc',
    'is:issue is:open grant "open source" "good first issue" sort:updated-desc',
    'is:issue is:open "AI agent" bounty reward sort:updated-desc',
    'is:issue is:open "MCP" bounty reward sort:updated-desc',
    # Targeted coverage for codegraphtheory paid issues
    'is:issue is:open repo:codegraphtheory/hermes-profile-template bounty reward sort:updated-desc',
    'is:issue is:open repo:codegraphtheory/hermes-profile-template bounty paid sort:updated-desc',
    'is:issue is:open repo:codegraphtheory/hermes-profile-template grant prize sort:updated-desc',
    'is:issue is:open user:codegraphtheory bounty reward sort:updated-desc',
    'is:issue is:open user:codegraphtheory bounty paid sort:updated-desc',
    'is:issue is:open user:codegraphtheory grant prize sort:updated-desc',
    # Targeted hackathon-tagged issues for cognee
    'is:issue is:open repo:topoteretes/cognee label:hackathon sort:updated-desc',
]

# ─── Spam / noise blocklist ───────────────────────────────────────────────────
BLOCKLIST = [
    "airdrop", "referral", "casino", "gambling", "trading bot",
    "phishing", "spam", "scam",
]

# ─── Required bounty signal + excluded labels ─────────────────────────────────
STRONG_BOUNTY_TERMS = [
    "reward", "rewards", "paid", "prize", "prizes", "grant", "grants",
    "payment", "payments", "paying", "payout", "payouts", "compensation",
    "compensated", "stipend", "stipends", "up for grabs",
    "opire", "gitcoin", "superfluid", "dework",
]

BOUNTY_CONTEXT_TERMS = [
    "bounty", "bounties", "quest", "quests", "mission", "missions",
    "challenge", "challenges",
]

MONETARY_HINTS = [
    "$", " usd", "usdc", "usdt", "btc", "eth", "sol", "hbar", "matic",
]

WORK_CUE_TERMS = [
    "fix", "build", "implement", "create", "write", "ship", "deliver",
    "task", "issue", "feature", "integration", "documentation", "tutorial",
    "article", "pr", "pull request", "bug",
]

EXCLUDED_LABELS = [
    "grantfox oss",
    "grantfox oss campaign",
    "maybe rewarded",
    "official campaign",
    "stellar wave",
    "drips-wave",
]

FALSE_POSITIVE_PATTERNS = [
    "bounty alert:",
    "create bounty fails",
    "dummy test quest",
    "dummy quest",
]

# ─── Repo blocklist (farming repos, self-repo) ────────────────────────────────
REPO_BLOCKLIST = [
    "SecureBananaLabs/bug-bounty",  # farming repo — bulk fake issues
    "greyw0rks/bountyscout",        # self — bot's own alert issues
    "dev-kp-eloper/bountyscout",    # upstream alert repo
]

TICKER_STATUS_RE = re.compile(r"^[^\w]*[A-Z]{2,5}\s+[—-]\s+\d{4}-\d{2}-\d{2}\s+\(OK\)$")
TARGETED_HACKATHON_REPOS = {
    "topoteretes/cognee",
}


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


def fetch_issue_timeline(repo: str, issue_number: int, token: str | None) -> list[dict]:
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/timeline"
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
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[WARN] Could not load timeline for {repo}#{issue_number}: {e}")
        return []


def count_linked_prs(item: dict, token: str | None) -> int:
    repo = item.get("repository_url", "").replace("https://api.github.com/repos/", "")
    issue_number = item.get("number")
    if not repo or not issue_number:
        return 0

    linked_prs: set[str] = set()
    for event in fetch_issue_timeline(repo, int(issue_number), token):
        source_issue = event.get("source", {}).get("issue", {})
        if not source_issue or "pull_request" not in source_issue:
            continue
        pr_ref = (
            source_issue.get("repository_url", ""),
            source_issue.get("number"),
            source_issue.get("html_url", ""),
        )
        linked_prs.add(str(pr_ref))

    return len(linked_prs)


def was_updated_recently(item: dict, now: datetime, window_hours: int = RECENT_WINDOW_HOURS) -> bool:
    updated_at = item.get("updated_at")
    if not updated_at:
        return False
    try:
        updated_dt = datetime.strptime(updated_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return False

    earliest_allowed = now - timedelta(hours=window_hours)
    return earliest_allowed <= updated_dt <= now


def passes_recency_and_pr_rules(item: dict, linked_prs: int, now: datetime) -> bool:
    if was_updated_recently(item, now):
        return linked_prs <= MAX_LINKED_PRS
    return linked_prs == 0


def extract_label_names(item: dict) -> list[str]:
    labels = item.get("labels", [])
    names: list[str] = []
    for label in labels:
        name = str(label.get("name", "")).strip().lower()
        if name:
            names.append(name)
    return names


def has_bounty_signal(item: dict) -> bool:
    title = str(item.get("title", "")).lower()
    body = str(item.get("body", "") or "").lower()
    label_names = extract_label_names(item)
    labels_text = " ".join(label_names)
    searchable = " ".join([title, body, labels_text])

    has_payment = (
        any(term in searchable for term in STRONG_BOUNTY_TERMS)
        or any(term in searchable for term in MONETARY_HINTS)
    )
    has_context = any(term in searchable for term in BOUNTY_CONTEXT_TERMS)
    has_paid_label = any(label in {"reward", "rewards", "paid", "grant", "grants", "prize", "prizes"} for label in label_names)
    has_bounty_label = any(label in {"bounty", "bounties"} for label in label_names)
    has_work_cue = any(term in searchable for term in WORK_CUE_TERMS)

    if not has_payment and not has_paid_label:
        return False

    return has_context or has_bounty_label or has_work_cue


def is_targeted_hackathon_issue(item: dict) -> bool:
    repo = item.get("repository_url", "").replace("https://api.github.com/repos/", "").lower()
    if repo not in TARGETED_HACKATHON_REPOS:
        return False

    label_names = extract_label_names(item)
    return "hackathon" in label_names


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
    label_names = extract_label_names(item)
    searchable = " ".join([title, body, " ".join(label_names)])

    if any(label in EXCLUDED_LABELS for label in label_names):
        return False

    if any(term in title or term in body for term in BLOCKLIST):
        return False

    if any(pattern in searchable for pattern in FALSE_POSITIVE_PATTERNS):
        return False

    if title.startswith("epic:"):
        return False

    if TICKER_STATUS_RE.match(str(item.get("title", "")).strip()):
        return False

    if not has_bounty_signal(item) and not is_targeted_hackathon_issue(item):
        return False

    return True


# ─── Notification senders ─────────────────────────────────────────────────────

def chunk_lines(lines: list[str], limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + (1 if current else 0)
        if current and current_len + line_len > limit:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line)
            continue
        current.append(line)
        current_len += line_len

    if current:
        chunks.append("\n".join(current))

    return chunks


def send_telegram(token: str, chat_id: str, message: str):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    sent_chunks = 0

    for chunk in chunk_lines(message.splitlines()):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
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
                sent_chunks += 1
        except urllib.error.HTTPError as e:
            print(f"[ERROR] Telegram failed with HTTP {e.code}. Check TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID and message size.")
            return
        except Exception as e:
            print(f"[ERROR] Telegram failed: {e}")
            return

    print(f"[OK] Telegram notification sent in {sent_chunks} chunk(s).")


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


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    github_token    = os.environ.get("GITHUB_TOKEN")
    telegram_token  = os.environ.get("TELEGRAM_BOT_TOKEN")
    telegram_chat   = os.environ.get("TELEGRAM_CHAT_ID")
    discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL")

    seen_urls = load_seen_bounties()
    new_bounties: list[dict] = []
    now = datetime.now(timezone.utc)
    stats = {
        "queries": len(SEARCH_QUERIES),
        "raw_matches": 0,
        "seen_skips": 0,
        "noise_rejections": 0,
        "pr_rejections": 0,
        "accepted": 0,
    }

    print(f"🔍 Scouting GitHub for active bounties with recent updates or zero linked PRs...")
    for query in SEARCH_QUERIES:
        results = search_github(query, github_token)
        time.sleep(2)  # stay under GitHub Search API rate limit (30 req/min)
        for item in results.get("items", []):
            stats["raw_matches"] += 1
            url = item.get("html_url")
            if not url or url in seen_urls:
                stats["seen_skips"] += 1
                continue
            if not is_clean_candidate(item):
                stats["noise_rejections"] += 1
                continue

            linked_prs = count_linked_prs(item, github_token)
            time.sleep(1)
            if not passes_recency_and_pr_rules(item, linked_prs, now):
                stats["pr_rejections"] += 1
                continue

            if url:
                new_bounties.append({
                    "title":      item.get("title"),
                    "url":        url,
                    "repo":       url.split("/issues/")[0].replace("https://github.com/", ""),
                    "comments":   item.get("comments", 0),
                    "linked_prs": linked_prs,
                    "updated_at": item.get("updated_at"),
                })
                seen_urls.add(url)
                stats["accepted"] += 1

    print(
        "[INFO] Scan summary: "
        f"queries={stats['queries']} "
        f"raw_matches={stats['raw_matches']} "
        f"seen_skips={stats['seen_skips']} "
        f"noise_rejections={stats['noise_rejections']} "
        f"pr_rejections={stats['pr_rejections']} "
        f"accepted={stats['accepted']}"
    )

    if not new_bounties:
        print("✅ No new bounties found this run.")
        return

    count = len(new_bounties)
    print(f"🎯 Discovered {count} NEW bounty opportunit{'ies' if count != 1 else 'y'}!")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    plural  = "ies" if count != 1 else "y"

    # ── Telegram / Discord message (Markdown) ────────────────────────────────
    lines = [
        f"Bounty Alert - {now_str}",
        f"Found {count} new opportunit{plural}:",
        "",
    ]
    for i, b in enumerate(new_bounties, 1):
        lines += [
            f"{i}. {b['title']}",
            f"   - Repo: {b['repo']}",
            f"   - Comments: {b['comments']}",
            f"   - Linked PRs: {b['linked_prs']}",
            f"   - Link: {b['url']}",
            "",
        ]
    notif_msg = "\n".join(lines)

    if telegram_token and telegram_chat:
        send_telegram(telegram_token, telegram_chat, notif_msg)

    if discord_webhook:
        send_discord(discord_webhook, notif_msg.replace("•", "-"))

    save_seen_bounties(seen_urls)
    print("💾 State saved.")


if __name__ == "__main__":
    main()
