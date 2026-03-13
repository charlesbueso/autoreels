"""
Meta Token Setup — run this once to:
  1. Exchange your short-lived user token for a long-lived user token (~60 days)
  2. Fetch the never-expiring Page Access Token
  3. Fetch your Instagram Business Account ID
  4. Write META_PAGE_ACCESS_TOKEN, META_PAGE_ID, META_IG_ACCOUNT_ID into .env.local

Usage:
    python scripts/meta_setup.py

You will be prompted for:
  - Your short-lived user token (from Graph API Explorer)
  - Your Meta App ID
  - Your Meta App Secret
"""

import sys
import re
from pathlib import Path

try:
    import httpx
except ImportError:
    sys.exit("httpx not installed. Run: pip install httpx")

ENV_PATH = Path(__file__).resolve().parent.parent / ".env.local"
GRAPH = "https://graph.facebook.com/v21.0"


def prompt(label: str, secret: bool = False) -> str:
    import getpass
    fn = getpass.getpass if secret else input
    val = fn(f"{label}: ").strip()
    if not val:
        sys.exit(f"❌ {label} is required.")
    return val


def update_env(key: str, value: str) -> None:
    """Replace or append a key=value line in .env.local."""
    content = ENV_PATH.read_text(encoding="utf-8")
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    new_line = f"{key}={value}"
    if pattern.search(content):
        content = pattern.sub(new_line, content)
    else:
        content = content.rstrip("\n") + f"\n{new_line}\n"
    ENV_PATH.write_text(content, encoding="utf-8")
    print(f"  ✅ Updated .env.local: {key}=...{value[-6:]}")


def main() -> None:
    print("\n🔐 Meta Token Setup for AutoReels\n")
    print("Paste your short-lived USER token from the Graph API Explorer.")
    print("Make sure it has these permissions:")
    print("  pages_show_list, pages_read_engagement, pages_manage_posts,")
    print("  publish_video, instagram_basic, instagram_content_publish\n")

    short_token = prompt("Short-lived user token")
    app_id      = prompt("Meta App ID")
    app_secret  = prompt("Meta App Secret", secret=True)

    # ── Step 1: Exchange for long-lived user token ─────────────────────────
    print("\n⏳ Exchanging for long-lived user token...")
    resp = httpx.get(f"{GRAPH}/oauth/access_token", params={
        "grant_type":        "fb_exchange_token",
        "client_id":         app_id,
        "client_secret":     app_secret,
        "fb_exchange_token": short_token,
    })
    data = resp.json()
    if "error" in data:
        sys.exit(f"❌ Token exchange failed: {data['error']}")
    long_user_token = data["access_token"]
    expires_in = data.get("expires_in", "unknown")
    print(f"  ✅ Long-lived user token obtained (expires in ~{int(expires_in)//86400} days)")

    # ── Step 2: Get Page Access Token (never expires) ──────────────────────
    print("\n⏳ Fetching your Facebook Pages...")
    resp = httpx.get(f"{GRAPH}/me/accounts", params={
        "access_token": long_user_token,
        "fields": "id,name,access_token",
    })
    data = resp.json()
    if "error" in data:
        sys.exit(f"❌ Could not fetch pages: {data['error']}")

    pages = data.get("data", [])
    if not pages:
        sys.exit("❌ No Facebook Pages found. Make sure pages_show_list permission was granted.")

    print()
    if len(pages) == 1:
        page = pages[0]
        print(f"  Found 1 page: {page['name']} (ID: {page['id']})")
    else:
        for i, p in enumerate(pages):
            print(f"  [{i}] {p['name']} (ID: {p['id']})")
        choice = input("\nEnter the number of your Matra page: ").strip()
        page = pages[int(choice)]

    page_id           = page["id"]
    page_access_token = page["access_token"]
    print(f"  ✅ Page: {page['name']}  |  ID: {page_id}")

    # ── Step 3: Get Instagram Business Account ID ──────────────────────────
    print("\n⏳ Fetching Instagram Business Account ID...")
    resp = httpx.get(f"{GRAPH}/{page_id}", params={
        "fields":       "instagram_business_account",
        "access_token": page_access_token,
    })
    data = resp.json()
    if "error" in data:
        sys.exit(f"❌ Could not fetch IG account: {data['error']}")

    ig_account = data.get("instagram_business_account")
    if not ig_account:
        sys.exit(
            "❌ No Instagram Business Account linked to this page.\n"
            "   Go to Instagram → Settings → Account Type → Switch to Professional Account,\n"
            "   then link it to your Facebook Page in Meta Business Suite."
        )
    ig_account_id = ig_account["id"]
    print(f"  ✅ Instagram Business Account ID: {ig_account_id}")

    # ── Step 4: Write to .env.local ────────────────────────────────────────
    print("\n⏳ Writing tokens to .env.local...")
    update_env("META_PAGE_ACCESS_TOKEN", page_access_token)
    update_env("META_PAGE_ID",           page_id)
    update_env("META_IG_ACCOUNT_ID",     ig_account_id)

    print("\n✨ Done! Your .env.local is now configured for Meta.")
    print("   The Page Access Token never expires (generated from a long-lived user token).")
    print("   Re-run this script every ~60 days to refresh it when your user token expires.\n")


if __name__ == "__main__":
    main()
