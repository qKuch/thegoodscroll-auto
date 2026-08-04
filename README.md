# Meme Bot pentru Instagram (Imgur → Instagram, prin GitHub Actions)

Bot care preia automat cele mai populare postări de tip imagine din
galeria publică "hot" de pe Imgur și le postează pe un cont Instagram
Business/Creator, cu credit pentru autorul original. Rulează integral pe
GitHub Actions — fără server propriu, fără cron local.

> **Notă istorică**: sursa inițială a proiectului a fost Reddit. Reddit
> a oprit accesul neautentificat la `.json` pe 28 mai 2026, iar
> auto-înregistrarea de aplicații OAuth Reddit e în prezent (aug 2026)
> blocată/nefuncțională din partea lor ("Responsible Builder Policy").
> Am trecut pe Imgur, care rămâne self-serve și mult mai simplu de
> configurat.

## Cum funcționează

1. `meme_bot.py` interoghează galeria publică "hot" de pe Imgur
   (`api.imgur.com/3/gallery/hot/viral/...`) — necesită doar un Client ID
   (fără login de utilizator, fără parolă).
2. Filtrează postările: elimină albume, conținut NSFW, tot ce nu e
   imagine directă (jpg/png), cele sub pragul de puncte configurat, și
   cele deja postate sau eșuate anterior (evidența e ținută în
   `posted_ids.json`). Opțional, poate filtra și după cuvinte-cheie
   (`IMGUR_TOPICS`) căutate în titlu/tag-uri.
3. Postează imaginea câștigătoare pe Instagram prin Graph API (Content
   Publishing API), cu un caption care include titlul, username-ul
   autorului (dacă există) și link către postarea originală pe Imgur.
4. Actualizează `posted_ids.json` și îl comite automat înapoi în repo,
   ca să persiste între rulările (efemere) ale GitHub Actions.
5. Workflow-ul GitHub Actions rulează scriptul la un interval fix
   (implicit: o dată la 6 ore).

### De ce commit automat pentru persistență?

Runner-ele GitHub Actions pornesc de la zero de fiecare dată — orice
fișier scris local dispare la finalul rulării. Opțiuni posibile: cache
de Actions (nesigur pe termen lung, poate fi evacuat), o bază de date
externă găzduită undeva, un Gist privat, sau — soluția aleasă aici —
**commit automat al `posted_ids.json` înapoi în branch, folosind
`GITHUB_TOKEN`-ul implicit**. E cea mai simplă soluție, nu necesită
infrastructură externă și e suficientă pentru volumul mic de date
implicat (o listă de ID-uri).

---

## Setup (o singură dată)

### 1. Cont Instagram Business sau Creator

- Contul trebuie să fie de tip **Business** sau **Creator** (nu
  personal) — din Instagram: Setări → Cont → Schimbă tip de cont.
- Trebuie **conectat la o Pagină de Facebook** (chiar și una nouă, fără
  urmăritori) — Graph API cere asta.

### 2. Aplicație pe Meta for Developers

1. Mergi pe https://developers.facebook.com/apps și creează o aplicație
   nouă, tip **Business**.
2. Adaugă produsul **Instagram Graph API** (poate apărea ca
   "Instagram" în lista de produse, în funcție de interfața curentă),
   folosind use case-ul **"API setup with Facebook login"**.
3. Adaugă și **Facebook Login for Business**, necesar pentru a genera
   token-ul de acces.

### 3. Obținerea `IG_USER_ID`

1. Din **Graph API Explorer**
   (https://developers.facebook.com/tools/explorer/), selectează
   aplicația ta, cu **User Token**.
2. Bifează permisiunile: `instagram_basic`, `instagram_content_publish`,
   `pages_show_list`, `pages_read_engagement`, `business_management`.
3. Rulează `GET me/accounts` — obții ID-ul Paginii de Facebook
   conectate.
4. Rulează `GET {page-id}?fields=instagram_business_account` (înlocuiește
   `{page-id}` cu ID-ul de mai sus) — răspunsul conține `IG_USER_ID`.

### 4. Obținerea unui token de acces de lungă durată

Token-ul din Graph API Explorer e valabil doar 1-2 ore. Trebuie
schimbat cu unul de lungă durată (~60 zile). Din **App settings →
Basic** îți iei `App ID` și `App Secret`, apoi lipești direct în bara
de adrese a browserului (nu trimite acest URL nimănui, conține
practic parola contului tău Instagram):

```
https://graph.facebook.com/v21.0/oauth/access_token
    ?grant_type=fb_exchange_token
    &client_id=<APP_ID>
    &client_secret=<APP_SECRET>
    &fb_exchange_token=<TOKEN_SCURT_DIN_EXPLORER>
```

Răspunsul conține `access_token`-ul de lungă durată — acesta e
`IG_ACCESS_TOKEN`.

### 5. Client ID Imgur

1. Cont Imgur (dacă nu ai deja) → https://imgur.com
2. Mergi pe https://api.imgur.com/oauth2/addclient
3. Completezi:
   - **Application name**: orice, ex. `thegoodscroll-bot`
   - **Authorization type**: **"Anonymous usage without user
     authorization"** — exact ce ne trebuie, nu necesită login de
     utilizator la fiecare rulare
   - **Email**: adresa ta
4. Confirmi „I'm not a robot" → **Submit**.
5. Primești imediat un **Client ID** — asta e `IMGUR_CLIENT_ID`. (Nu ai
   nevoie de Client Secret pentru acest tip de acces.)

### 6. Adăugarea secretelor în GitHub

În repo → **Settings → Secrets and variables → Actions → New
repository secret**:

| Nume | Valoare |
|---|---|
| `IG_USER_ID` | ID-ul obținut la pasul 3 |
| `IG_ACCESS_TOKEN` | token-ul de lungă durată de la pasul 4 |
| `IMGUR_CLIENT_ID` | Client ID-ul de la pasul 5 |

Opțional, în **Settings → Secrets and variables → Actions → Variables**
(nu sunt secrete, doar configurare, cu valori implicite dacă lipsesc):

| Nume | Exemplu | Implicit dacă lipsește |
|---|---|---|
| `IMGUR_TOPICS` | `meme,funny,wholesome` | gol (fără filtrare tematică) |
| `MIN_UPVOTES` | `2000` | `1000` |
| `POST_LIMIT_PER_RUN` | `1` | `1` |

### 7. Pune fișierele în repo

Adaugă toate fișierele livrate (inclusiv `.github/workflows/meme_bot.yml`
și `posted_ids.json`) în repo și fă push. GitHub Actions detectează
automat workflow-ul din `.github/workflows/`.

---

## Ce rulează complet automat, fără intervenția ta

După setup-ul de mai sus:

- Workflow-ul pornește singur, conform programului `cron` (implicit la
  fiecare 6 ore — editabil în `.github/workflows/meme_bot.yml`).
- Scriptul verifică galeria Imgur, alege cea mai potrivită postare
  nouă, o publică pe Instagram și actualizează `posted_ids.json`.
- Modificarea e comisă automat înapoi în repo — nu trebuie să faci
  nimic manual.
- Poți declanșa și o rulare manuală oricând din tab-ul **Actions** →
  **Meme Bot** → **Run workflow** (util pentru testare).

Singurul lucru care necesită intervenție periodică e token-ul de
Instagram (Imgur Client ID-ul nu expiră).

## Reînnoirea token-ului Instagram (la ~60 de zile)

Token-ul de lungă durată emis de Meta expiră după aproximativ 60 de
zile. Înainte de expirare:

1. Repetă schimbul de la pasul 4, folosind **token-ul curent, încă
   valid**, ca `fb_exchange_token` — primești un nou token valabil alte
   60 de zile.
2. Actualizează secretul `IG_ACCESS_TOKEN` din GitHub cu noua valoare.

**Recomandare:** pune-ți un memento recurent (calendar) la ~50 de zile,
ca să nu prinzi token-ul expirat.

## Note importante

- **Drepturi de autor**: bot-ul include mereu creditul sursei
  (username Imgur sau „anonymous Imgur user" dacă postarea nu are
  autor asociat), dar redistribuirea conținutului altora poate implica
  probleme de drepturi de autor sau poate încălca termenii
  Imgur/Instagram, indiferent de credit — verifică termenii ambelor
  platforme, mai ales dacă intenționezi să rulezi bot-ul la scară mare.
- **Limitări Instagram**: Graph API cere ca imaginea să respecte un
  anumit raport de aspect (~4:5 până la 1.91:1); imaginile care nu se
  încadrează vor eșua la publicare — scriptul le marchează ca eșuate
  (`failed`) și trece la următorul candidat, ca să nu reîncerce la
  infinit aceeași postare.
- **`IMGUR_TOPICS`**: fără el, bot-ul ia orice din galeria "hot"
  generală a Imgur (foarte orientată spre meme-uri/conținut viral din
  cultura Imgur). Cu el, filtrează după cuvinte găsite în titlu sau
  tag-urile postării — nu e la fel de precis ca un subreddit dedicat,
  dar apropie rezultatul de o temă anume.
- **`FETCH_PAGES`**: câte pagini din galeria "hot" se preiau per
  rulare (implicit 1, ~60 de postări) — crește dacă vrei un bazin mai
  mare de candidați.

## Structura proiectului

```
.
├── meme_bot.py                       # scriptul principal
├── requirements.txt                  # dependinte Python
├── posted_ids.json                   # evidenta ID-urilor (se actualizeaza automat)
├── README.md
└── .github/
    └── workflows/
        └── meme_bot.yml              # workflow-ul GitHub Actions
```
