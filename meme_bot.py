"""
meme_bot.py

Preia postările "hot" din subreddit-uri configurabile (API JSON public,
fara autentificare), le filtreaza dupa un minim de upvote-uri si exclude
imaginile deja postate, apoi posteaza cea mai buna postare noua pe
Instagram (cont Business/Creator) prin Graph API.

Variabile de mediu necesare:
    IG_USER_ID        - ID-ul contului Instagram Business/Creator
    IG_ACCESS_TOKEN   - token de acces (long-lived) pentru Graph API

Variabile de mediu optionale:
    SUBREDDITS         - lista de subreddit-uri, separate prin virgula
                          (implicit: "memes,wholesomememes")
    MIN_UPVOTES         - prag minim de upvote-uri (implicit: 1000)
    POST_LIMIT_PER_RUN  - cate postari noi se publica per rulare (implicit: 1)
    FETCH_LIMIT         - cate postari "hot" se preiau per subreddit (implicit: 25)
    POSTED_IDS_FILE     - calea catre fisierul de evidenta (implicit: posted_ids.json)
    REDDIT_USER_AGENT   - User-Agent trimis catre Reddit
"""

import json
import logging
import os
import time
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("meme_bot")

# ---------------------------------------------------------------------------
# Configurare
# ---------------------------------------------------------------------------

SUBREDDITS = [
    s.strip()
    for s in (os.environ.get("SUBREDDITS") or "memes,wholesomememes").split(",")
    if s.strip()
]
MIN_UPVOTES = int(os.environ.get("MIN_UPVOTES") or "1000")
POST_LIMIT_PER_RUN = int(os.environ.get("POST_LIMIT_PER_RUN") or "1")
FETCH_LIMIT = int(os.environ.get("FETCH_LIMIT") or "25")
POSTED_IDS_FILE = Path(os.environ.get("POSTED_IDS_FILE") or "posted_ids.json")

IG_USER_ID = os.environ.get("IG_USER_ID")
IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN")

REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT") or (
    "meme-bot/1.0 (github actions; contact: set REDDIT_USER_AGENT)"
)

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


# ---------------------------------------------------------------------------
# Evidenta ID-urilor deja procesate
# ---------------------------------------------------------------------------

def load_seen_ids():
    """Returneaza (posted_ids, failed_ids) ca seturi.

    posted_ids = postari publicate cu succes
    failed_ids = postari care au esuat definitiv la publicare (nu se
                 mai reincearca, de ex. raport de aspect nepermis)
    """
    if POSTED_IDS_FILE.exists():
        try:
            with open(POSTED_IDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data.get("posted", [])), set(data.get("failed", []))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(
                f"Nu am putut citi {POSTED_IDS_FILE}: {e}. Pornesc de la liste goale."
            )
    return set(), set()


def save_seen_ids(posted_ids, failed_ids):
    data = {
        "posted": sorted(posted_ids),
        "failed": sorted(failed_ids),
    }
    with open(POSTED_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Reddit
# ---------------------------------------------------------------------------

def fetch_hot_posts(subreddit, limit=25):
    url = f"https://www.reddit.com/r/{subreddit}/hot.json"
    headers = {"User-Agent": REDDIT_USER_AGENT}
    params = {"limit": limit}
    resp = requests.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    return [child["data"] for child in payload["data"]["children"]]


def is_direct_image_url(url):
    if not url:
        return False
    lower = url.lower().split("?")[0]
    return lower.endswith(IMAGE_EXTENSIONS)


def find_candidates():
    """Aduna postari eligibile din toate subreddit-urile, sortate descrescator dupa scor."""
    candidates = []
    for sub in SUBREDDITS:
        try:
            posts = fetch_hot_posts(sub, FETCH_LIMIT)
        except requests.RequestException as e:
            logger.error(f"Eroare la preluarea r/{sub}: {e}")
            continue

        for post in posts:
            if post.get("stickied") or post.get("over_18"):
                continue
            if post.get("score", 0) < MIN_UPVOTES:
                continue

            image_url = post.get("url_overridden_by_dest") or post.get("url")
            is_image_hint = post.get("post_hint") == "image"
            if not (is_image_hint and is_direct_image_url(image_url)):
                continue

            candidates.append(
                {
                    "id": post["id"],
                    "subreddit": post.get("subreddit", sub),
                    "author": post.get("author", "unknown"),
                    "title": (post.get("title") or "").strip(),
                    "score": post.get("score", 0),
                    "image_url": image_url,
                    "permalink": f"https://reddit.com{post.get('permalink', '')}",
                }
            )

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


# ---------------------------------------------------------------------------
# Instagram Graph API
# ---------------------------------------------------------------------------

def build_caption(post):
    title = post["title"]
    if len(title) > 200:
        title = title[:197] + "..."
    return (
        f"{title}\n\n"
        f"📸 Credit: u/{post['author']} din r/{post['subreddit']}\n"
        f"🔗 {post['permalink']}\n\n"
        f"#memes #{post['subreddit']}"
    )


def create_media_container(image_url, caption):
    url = f"{GRAPH_BASE}/{IG_USER_ID}/media"
    payload = {
        "image_url": image_url,
        "caption": caption,
        "access_token": IG_ACCESS_TOKEN,
    }
    resp = requests.post(url, data=payload, timeout=30)
    data = resp.json()
    if resp.status_code != 200 or "id" not in data:
        raise RuntimeError(f"Eroare la crearea containerului media: {data}")
    return data["id"]


def wait_for_container_ready(creation_id, max_attempts=10, delay=3):
    """Instagram proceseaza imaginea async; asteptam status FINISHED inainte de publish."""
    url = f"{GRAPH_BASE}/{creation_id}"
    for _ in range(max_attempts):
        resp = requests.get(
            url,
            params={"fields": "status_code", "access_token": IG_ACCESS_TOKEN},
            timeout=15,
        )
        data = resp.json()
        status = data.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Procesare esuata pentru containerul {creation_id}: {data}")
        time.sleep(delay)
    raise TimeoutError(f"Containerul {creation_id} nu a fost gata in timp util.")


def publish_media(creation_id):
    url = f"{GRAPH_BASE}/{IG_USER_ID}/media_publish"
    payload = {
        "creation_id": creation_id,
        "access_token": IG_ACCESS_TOKEN,
    }
    resp = requests.post(url, data=payload, timeout=30)
    data = resp.json()
    if resp.status_code != 200 or "id" not in data:
        raise RuntimeError(f"Eroare la publicare: {data}")
    return data["id"]


def post_to_instagram(post):
    caption = build_caption(post)
    logger.info(f"Creez container media pentru postarea {post['id']} ({post['image_url']})")
    creation_id = create_media_container(post["image_url"], caption)
    wait_for_container_ready(creation_id)
    media_id = publish_media(creation_id)
    logger.info(f"Postat cu succes pe Instagram. Media ID: {media_id}")
    return media_id


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not IG_USER_ID or not IG_ACCESS_TOKEN:
        raise SystemExit("Lipsesc variabilele de mediu IG_USER_ID / IG_ACCESS_TOKEN.")

    posted_ids, failed_ids = load_seen_ids()
    seen_ids = posted_ids | failed_ids

    candidates = find_candidates()
    logger.info(f"Am gasit {len(candidates)} postari candidate (inainte de filtrarea duplicatelor).")

    new_candidates = [c for c in candidates if c["id"] not in seen_ids]
    logger.info(f"{len(new_candidates)} postari noi, neprocesate inca.")

    if not new_candidates:
        logger.info("Nimic nou de postat.")
        return

    posted_count = 0
    for post in new_candidates:
        if posted_count >= POST_LIMIT_PER_RUN:
            break
        try:
            post_to_instagram(post)
            posted_ids.add(post["id"])
            posted_count += 1
        except Exception as e:
            logger.error(f"Esec definitiv la postarea {post['id']}: {e}")
            failed_ids.add(post["id"])
        finally:
            # salvam dupa fiecare incercare, ca sa nu pierdem progresul
            # daca o incercare ulterioara arunca o eroare neasteptata
            save_seen_ids(posted_ids, failed_ids)

    logger.info(f"Rulare completa. Postari noi publicate: {posted_count}.")


if __name__ == "__main__":
    main()
