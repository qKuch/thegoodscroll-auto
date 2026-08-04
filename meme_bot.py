"""
meme_bot.py

Preia postari populare ("hot") din galeria publica Imgur, le filtreaza
dupa un minim de puncte (upvote-uri) si exclude imaginile deja postate,
apoi posteaza cea mai buna postare noua pe Instagram (cont Business/Creator)
prin Graph API.

Nota: sursa initiala a fost Reddit, dar Reddit a oprit accesul neautentificat
la endpoint-urile .json pe 28 mai 2026, iar auto-inregistrarea de aplicatii
OAuth Reddit e in prezent (aug 2026) nefunctionala/blocata manual de Reddit
("Responsible Builder Policy"). Imgur ramane self-serve si necesita doar un
Client ID (fara login de utilizator) pentru acces citire la galeria publica.

Variabile de mediu necesare:
    IG_USER_ID          - ID-ul contului Instagram Business/Creator
    IG_ACCESS_TOKEN      - token de acces (long-lived) pentru Graph API
    IMGUR_CLIENT_ID       - Client ID-ul aplicatiei Imgur (tip "Anonymous
                            usage without user authorization")

Variabile de mediu optionale:
    IMGUR_TOPICS        - cuvinte-cheie (separate prin virgula) cautate in
                          titlu/tag-urile postarii, pentru filtrare tematica
                          (implicit: gol = fara filtrare, doar "hot" general)
    MIN_UPVOTES         - prag minim de puncte Imgur (implicit: 1000)
    POST_LIMIT_PER_RUN  - cate postari noi se publica per rulare (implicit: 1)
    FETCH_PAGES         - cate pagini din galeria "hot" se preiau, cate
                          ~60 postari fiecare (implicit: 1)
    POSTED_IDS_FILE     - calea catre fisierul de evidenta (implicit: posted_ids.json)
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

# Notă: folosim `os.environ.get("X") or "default"` in loc de
# `os.environ.get("X", "default")` pentru ca GitHub Actions seteaza
# variabila ca string gol ('') cand un Repository Variable nu e definit,
# nu o omite complet — iar .get() cu valoare implicita nu prinde cazul asta.
IMGUR_TOPICS = [
    s.strip().lower()
    for s in (os.environ.get("IMGUR_TOPICS") or "").split(",")
    if s.strip()
]
MIN_UPVOTES = int(os.environ.get("MIN_UPVOTES") or "1000")
POST_LIMIT_PER_RUN = int(os.environ.get("POST_LIMIT_PER_RUN") or "1")
FETCH_PAGES = int(os.environ.get("FETCH_PAGES") or "1")
POSTED_IDS_FILE = Path(os.environ.get("POSTED_IDS_FILE") or "posted_ids.json")

IG_USER_ID = os.environ.get("IG_USER_ID")
IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN")

IMGUR_CLIENT_ID = os.environ.get("IMGUR_CLIENT_ID")

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

IMGUR_API_BASE = "https://api.imgur.com/3"
ALLOWED_MIME_TYPES = ("image/jpeg", "image/png")


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
# Imgur (galeria publica "hot" — necesita doar Client ID, fara login)
# ---------------------------------------------------------------------------

def fetch_hot_gallery_page(page):
    url = f"{IMGUR_API_BASE}/gallery/hot/viral/{page}.json"
    headers = {
        "Authorization": f"Client-ID {IMGUR_CLIENT_ID}",
        "User-Agent": "thegoodscroll-bot/1.0",
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("success"):
        raise RuntimeError(f"Raspuns Imgur nereusit: {payload}")
    return payload.get("data") or []


def matches_topics(item):
    """Fara IMGUR_TOPICS configurat, acceptam orice postare din galeria hot."""
    if not IMGUR_TOPICS:
        return True
    title = (item.get("title") or "").lower()
    tag_names = [t.get("name", "").lower() for t in (item.get("tags") or [])]
    haystack = title + " " + " ".join(tag_names)
    return any(topic in haystack for topic in IMGUR_TOPICS)


def find_candidates():
    """Aduna postari eligibile din galeria hot Imgur, sortate descrescator dupa scor."""
    candidates = []
    for page in range(FETCH_PAGES):
        try:
            items = fetch_hot_gallery_page(page)
        except requests.RequestException as e:
            logger.error(f"Eroare la preluarea paginii {page} din galeria Imgur: {e}")
            continue

        for item in items:
            if item.get("is_album"):
                continue
            if item.get("nsfw"):
                continue
            if item.get("type") not in ALLOWED_MIME_TYPES:
                continue

            score = item.get("points")
            if score is None:
                score = item.get("ups", 0) or 0
            if score < MIN_UPVOTES:
                continue

            if not matches_topics(item):
                continue

            image_url = item.get("link")
            if not image_url:
                continue

            candidates.append(
                {
                    "id": item["id"],
                    "author": item.get("account_url") or None,
                    "title": (item.get("title") or "").strip() or "Untitled",
                    "score": score,
                    "image_url": image_url,
                    "permalink": f"https://imgur.com/gallery/{item['id']}",
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

    if post["author"]:
        credit_line = f"📸 Credit: {post['author']} (via Imgur)"
    else:
        credit_line = "📸 Credit: anonymous Imgur user"

    return (
        f"{title}\n\n"
        f"{credit_line}\n"
        f"🔗 {post['permalink']}\n\n"
        f"#memes #imgur"
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
    if not IMGUR_CLIENT_ID:
        raise SystemExit("Lipseste variabila de mediu IMGUR_CLIENT_ID.")

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
