"""
meme_bot.py

Preia postari populare din doua surse independente — Tumblr (postari cu
tag-uri configurabile) si Humor API — le filtreaza dupa un prag minim de
scor si exclude imaginile deja postate, apoi posteaza cea mai buna postare
noua pe Instagram (cont Business/Creator) prin Graph API.

Nota istorica: sursa initiala a fost Reddit, inlocuita cu Imgur dupa ce
Reddit a oprit accesul neautentificat la .json (28 mai 2026) si a blocat
si inregistrarea de aplicatii OAuth noi. Imgur a fost la randul lui
inlocuit cu Tumblr, galeria generala "hot" a Imgur nemaifiind suficient
de orientata spre meme-uri.

Fiecare sursa e activata independent, doar daca cheia ei e configurata —
daca lipseste una, bot-ul continua cu cealalta, fara sa pice.

Variabile de mediu necesare:
    IG_USER_ID          - ID-ul contului Instagram Business/Creator
    IG_ACCESS_TOKEN      - token de acces (long-lived) pentru Graph API
    (+ cel putin una din urmatoarele doua)
    TUMBLR_API_KEY        - consumer key de la aplicatia Tumblr inregistrata
    HUMOR_API_KEY         - API key de la humorapi.com

Variabile de mediu optionale:
    TUMBLR_TAGS          - tag-uri Tumblr (separate prin virgula), ex.
                          "memes,funny" (implicit: "memes")
    MIN_NOTES_TUMBLR     - prag minim de note (like-uri + reblog-uri) pe
                          Tumblr (implicit: 20 — feed-ul /tagged pare sa
                          fie predominant cronologic, nu neaparat sortat
                          dupa popularitate, deci postarile proaspete au
                          adesea 0 note; un prag mare le exclude pe toate)
    TUMBLR_FETCH_LIMIT   - cate postari se preiau per tag Tumblr per
                          rulare (implicit: 20)
    HUMOR_API_KEYWORDS   - cuvinte-cheie pentru Humor API (separate prin
                          virgula), optional (implicit: fara filtrare)
    MIN_RATING_HUMORAPI  - prag minim de rating Humor API, scala 0-10
                          (implicit: 7)
    HUMOR_API_COUNT      - cate apeluri separate se fac catre Humor API per
                          rulare (endpoint-ul intoarce un singur meme per
                          apel) (implicit: 3 — planul gratuit are o cota
                          zilnica mica; verifica humorapi.com/dashboard
                          pentru cota reala si ajusteaza daca permite mai mult)
    POST_LIMIT_PER_RUN   - cate postari noi se publica per rulare (implicit: 1)
    POSTED_IDS_FILE      - calea catre fisierul de evidenta (implicit: posted_ids.json)
"""

import json
import logging
import os
import re
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
TUMBLR_TAGS = [
    s.strip().lower()
    for s in (os.environ.get("TUMBLR_TAGS") or "memes").split(",")
    if s.strip()
]
MIN_NOTES_TUMBLR = int(os.environ.get("MIN_NOTES_TUMBLR") or "20")
TUMBLR_FETCH_LIMIT = int(os.environ.get("TUMBLR_FETCH_LIMIT") or "20")

HUMOR_API_KEYWORDS = [
    s.strip()
    for s in (os.environ.get("HUMOR_API_KEYWORDS") or "").split(",")
    if s.strip()
]
MIN_RATING_HUMORAPI = float(os.environ.get("MIN_RATING_HUMORAPI") or "7")
HUMOR_API_COUNT = int(os.environ.get("HUMOR_API_COUNT") or "3")

POST_LIMIT_PER_RUN = int(os.environ.get("POST_LIMIT_PER_RUN") or "1")
POSTED_IDS_FILE = Path(os.environ.get("POSTED_IDS_FILE") or "posted_ids.json")

IG_USER_ID = os.environ.get("IG_USER_ID")
IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN")

TUMBLR_API_KEY = os.environ.get("TUMBLR_API_KEY")
HUMOR_API_KEY = os.environ.get("HUMOR_API_KEY")

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

TUMBLR_API_BASE = "https://api.tumblr.com/v2"
HUMOR_API_BASE = "https://api.humorapi.com"
ALLOWED_MIME_TYPES = ("image/jpeg", "image/png")


# ---------------------------------------------------------------------------
# Evidenta ID-urilor deja procesate
# ---------------------------------------------------------------------------

def load_seen_ids():
    """Returneaza (posted_ids, failed_ids) ca seturi.

    posted_ids = postari publicate cu succes
    failed_ids = postari care au esuat definitiv la publicare (nu se
                 mai reincearca, de ex. raport de aspect nepermis)

    ID-urile sunt prefixate cu sursa (ex. "tumblr:123", "humorapi:6696")
    ca sa nu se poata suprapune intre cele doua surse.
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
# Sursa 1: Tumblr (postari cu un tag anume, din tot Tumblr — nu doar dintr-un
# blog — necesita doar un API key/consumer key, fara login de utilizator)
# ---------------------------------------------------------------------------

def fetch_tumblr_tagged(tag, limit):
    url = f"{TUMBLR_API_BASE}/tagged"
    params = {
        "tag": tag,
        "api_key": TUMBLR_API_KEY,
        "limit": limit,
        "filter": "text",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    response = payload.get("response")
    if response is None:
        raise RuntimeError(f"Raspuns Tumblr neasteptat pentru tag '{tag}': {payload}")
    # endpoint-ul /tagged intoarce direct o lista; alte endpoint-uri Tumblr
    # o pun sub o cheie "posts" — tratam ambele variante ca sa fim robusti
    if isinstance(response, dict):
        return response.get("posts") or []
    return response


IMG_SRC_RE = re.compile(r'<img[^>]+src="([^"]+)"')


def extract_tumblr_image_url(post):
    """Tumblr modern marcheaza majoritatea postarilor ca type='text', chiar
    si cand contin imagini — imaginea e in HTML-ul din 'body', nu intr-un
    array 'photos' separat (asta mai apare doar la postari-foto vechi)."""
    photos = post.get("photos") or []
    if photos:
        url = (photos[0].get("original_size") or {}).get("url")
        if url:
            return url

    body = post.get("body") or ""
    match = IMG_SRC_RE.search(body)
    if match:
        return match.group(1)

    return None


def find_tumblr_candidates():
    """Aduna postari eligibile de pe Tumblr, sortate descrescator dupa note."""
    if not TUMBLR_API_KEY:
        logger.info("TUMBLR_API_KEY lipseste — sar peste sursa Tumblr.")
        return []

    candidates = []
    seen_post_ids = set()

    for tag in TUMBLR_TAGS:
        try:
            posts = fetch_tumblr_tagged(tag, TUMBLR_FETCH_LIMIT)
        except requests.RequestException as e:
            logger.error(f"Eroare la preluarea tag-ului Tumblr '{tag}': {e}")
            continue

        if posts:
            logger.info(f"[DEBUG TEMPORAR] Prima postare Tumblr bruta: {json.dumps(posts[0])[:3000]}")

        for post in posts:
            post_id = post.get("id")
            if not post_id or post_id in seen_post_ids:
                continue
            seen_post_ids.add(post_id)

            if post.get("is_nsfw"):
                continue

            note_count = post.get("note_count", 0) or 0
            if note_count < MIN_NOTES_TUMBLR:
                continue

            image_url = extract_tumblr_image_url(post)
            if not image_url or is_blocked_domain(image_url):
                continue

            title = (post.get("summary") or "").strip() or "Meme"

            candidates.append(
                {
                    "id": f"tumblr:{post_id}",
                    "source": "tumblr",
                    "title": title,
                    "score": note_count,
                    "image_url": image_url,
                    "permalink": post.get("post_url"),
                }
            )

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


# ---------------------------------------------------------------------------
# Sursa 2: Humor API (humorapi.com) — baza dedicata de meme-uri, cu API
# key gratuit. Nu ofera (dupa cate am gasit in documentatie) atribuire
# individuala pe autor/sursa per meme.
# ---------------------------------------------------------------------------

REDDIT_HOSTED_DOMAINS = ("redd.it",)


def is_blocked_domain(image_url):
    """Instagram refuza sa preia imagini gazduite pe domenii Reddit
    (i.redd.it, preview.redd.it etc.) — filtram preventiv, ca sa nu
    incercam publicarea unei postari care va esua oricum."""
    return any(domain in image_url for domain in REDDIT_HOSTED_DOMAINS)


def fetch_humorapi_memes(count):
    """Endpoint-ul /memes/random intoarce mereu un singur meme per apel,
    indiferent de parametrul 'number' — facem `count` apeluri separate ca
    sa avem un bazin de candidati, nu doar unul."""
    url = f"{HUMOR_API_BASE}/memes/random"
    params = {
        "api-key": HUMOR_API_KEY,
        "min-rating": MIN_RATING_HUMORAPI,
    }
    if HUMOR_API_KEYWORDS:
        params["keywords"] = ",".join(HUMOR_API_KEYWORDS)

    memes = []
    seen_meme_ids = set()
    for _ in range(count):
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        payload = resp.json()

        meme = None
        payload_memes = payload.get("memes")
        if payload_memes:
            meme = payload_memes[0]
        elif payload.get("url"):
            meme = payload

        if meme and meme.get("id") not in seen_meme_ids:
            seen_meme_ids.add(meme.get("id"))
            memes.append(meme)

    return memes


def find_humorapi_candidates():
    """Aduna meme-uri eligibile de la Humor API, sortate descrescator dupa rating."""
    if not HUMOR_API_KEY:
        logger.info("HUMOR_API_KEY lipseste — sar peste sursa Humor API.")
        return []

    try:
        memes = fetch_humorapi_memes(HUMOR_API_COUNT)
    except requests.RequestException as e:
        logger.error(f"Eroare la preluarea meme-urilor de la Humor API: {e}")
        return []

    candidates = []
    for meme in memes:
        meme_id = meme.get("id")
        if meme_id is None:
            continue

        mime_type = meme.get("type")
        if mime_type and mime_type not in ALLOWED_MIME_TYPES:
            continue

        image_url = meme.get("url")
        if not image_url or is_blocked_domain(image_url):
            continue

        rating = meme.get("rating", MIN_RATING_HUMORAPI)

        candidates.append(
            {
                "id": f"humorapi:{meme_id}",
                "source": "humorapi",
                "title": (meme.get("title") or meme.get("caption") or "").strip() or "Meme",
                "score": rating,
                "image_url": image_url,
                "permalink": None,
            }
        )

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


# ---------------------------------------------------------------------------
# Combinarea surselor
# ---------------------------------------------------------------------------

def find_candidates():
    """Combina cele doua surse, alternand intre ele — NU sortam direct dupa
    scor intre surse, pentru ca scalele nu sunt comparabile (note Tumblr,
    potential in mii, vs. rating Humor API intre 0 si 10). In schimb,
    fiecare sursa e deja sortata intern dupa propriul scor, iar aici doar
    le intercalam, ca ambele sa aiba sanse egale sa fie alese per rulare."""
    tumblr_candidates = find_tumblr_candidates()
    humorapi_candidates = find_humorapi_candidates()

    logger.info(
        f"Candidati gasiti — Tumblr: {len(tumblr_candidates)}, "
        f"Humor API: {len(humorapi_candidates)}."
    )

    merged = []
    i = j = 0
    while i < len(tumblr_candidates) or j < len(humorapi_candidates):
        if i < len(tumblr_candidates):
            merged.append(tumblr_candidates[i])
            i += 1
        if j < len(humorapi_candidates):
            merged.append(humorapi_candidates[j])
            j += 1
    return merged


# ---------------------------------------------------------------------------
# Instagram Graph API
# ---------------------------------------------------------------------------

def build_caption(post):
    title = post["title"]
    if len(title) > 200:
        title = title[:197] + "..."

    if post["source"] == "tumblr":
        credit_line = "Via Tumblr"
        link_line = f"🔗 {post['permalink']}\n\n" if post["permalink"] else ""
        hashtags = "#memes #tumblr"
    else:
        credit_line = "Via Humor API"
        link_line = ""
        hashtags = "#memes"

    return f"{title}\n\n{credit_line}\n{link_line}{hashtags}"


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
    if not TUMBLR_API_KEY and not HUMOR_API_KEY:
        raise SystemExit(
            "Lipsesc ambele surse — seteaza cel putin TUMBLR_API_KEY sau HUMOR_API_KEY."
        )

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
