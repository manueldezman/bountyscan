# 🎯 BountyScout

Automated GitHub bounty scanner — runs **hourly** via GitHub Actions, surfaces new paid bounty issues, and pings you once per bounty via Telegram or Discord.

Forked from [dev-kp-eloper/BountyScout](https://github.com/dev-kp-eloper/BountyScout) and tuned for Web3 / hackathon ecosystems (Hedera, Celo, Stacks, Base, Mantle, LangChain).

---

## How It Works

1. **Scheduled trigger** — GitHub Actions cron fires at `17 * * * *` (17 minutes past each hour).
2. **Scouts GitHub** — Runs explicit-paid bounty searches instead of broad bounty/quest/task searches.
3. **Triages candidates** — Skips PRs, already-assigned issues, overcrowded threads (>25 comments), spam keywords, false-positive bounty-system tickets, and issues that fail the linked-PR recency rule.
4. **Deduplicates** — Compares against `seen_bounties.json`; only surfaces truly new entries.
5. **Notifies** — Dispatches via your configured channel(s).
6. **Persists state** — Commits updated `seen_bounties.json` back to the repo so you never get duplicates.

---

## Setup

### 1. Fork / create this repo

Push all three files to a new GitHub repo:

```
BountyScout/
├── .github/
│   └── workflows/
│       └── bounty-scout.yml
├── scout_bounties.py
├── seen_bounties.json
└── README.md
```

### 2. Choose your notification channel

#### Option A — Telegram
1. Message `@BotFather` → `/newbot` → copy the **API Token**
2. Send a message to your bot, then open `https://api.telegram.org/botTOKEN/getUpdates` and copy the numeric `chat.id`
3. Add repo secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. Large alert batches are automatically split into multiple Telegram messages.

#### Option B — Discord
1. Channel Settings → Integrations → Webhooks → Create Webhook → copy URL
2. Add repo secret: `DISCORD_WEBHOOK_URL`

### 3. Trigger manually to test

Actions tab → **Scout Active Bounties Hourly** → **Run workflow**

---

## Search Keywords

The scanner runs these query groups by default, focused on explicit paid opportunities:

| Category | Queries |
|---|---|
| Generic | `bounty reward`, `bounty paid`, `bounty prize`, `bounty grant`, `bounty payout`, `paid issue` |
| Paid signals | `reward $`, `reward USDC`, `reward ETH`, `up for grabs reward` |
| Platforms | `Opire reward`, `Gitcoin grant`, `Superfluid bounty reward`, `Dework task reward`, `hackathon prize TypeScript` |
| Targeted repos | `repo:codegraphtheory/hermes-profile-template` + `user:codegraphtheory` paid bounty/grant/prize searches |

Edit `SEARCH_QUERIES` in `scout_bounties.py` to add or remove terms. Adjust `RECENT_WINDOW_HOURS` if you want a different recent-issue window.

---

## Spam Filters

Issues are dropped if they contain any of: `airdrop`, `referral`, `casino`, `gambling`, `trading bot`, `phishing`, `spam`, `scam`.

Edit `BLOCKLIST` in `scout_bounties.py` to tune.

Issues are also dropped unless they contain explicit payment signals such as `reward`, `paid`, `prize`, `grant`, `payout`, `payment`, or a money/token amount. A `bounty` mention or label helps, but is not enough on its own.

Excluded labels currently include: `GRANTFOX OSS`, `GrantFox OSS campaign`, `MAYBE REWARDED`, `OFFICIAL CAMPAIGN`, `Stellar Wave`, and `drips-wave`.
Known false-positive patterns such as `Bounty Alert`, `Create Bounty fails`, dummy test quests, and stock ticker status posts are also rejected.

---

## PR Threshold

The scanner uses GitHub issue timeline references to count linked pull requests:

- Issues updated within the last hour are allowed with `0` or `1` linked PRs.
- Issues older than 1 hour are only allowed with `0` linked PRs.

Adjust `MAX_LINKED_PRS` or `RECENT_WINDOW_HOURS` in `scout_bounties.py` to change that behavior.
