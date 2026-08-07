# Meme Bot pentru Instagram + Facebook (prin GitHub Actions)

Bot care preia automat postări populare de tip imagine din **două surse
independente** — Tumblr (postări cu tag-uri configurabile) și Humor API —
și le postează pe un cont Instagram Business/Creator. Opțional, poate
posta simultan și pe o Pagină de Facebook, cu poze de la Picsum Photos
(flux complet separat, nu meme-uri). Rulează integral pe GitHub Actions
— fără server propriu, fără cron local.

> **Notă istorică**: sursa inițială a proiectului a fost Reddit, apoi
> Imgur. Reddit a oprit accesul neautentificat la `.json` pe 28 mai 2026
> și a blocat și auto-înregistrarea de aplicații OAuth noi
> ("Responsible Builder Policy"). Imgur a fost la rândul lui înlocuit —
> galeria lui generală "hot" nu mai e suficient de orientată spre
> meme-uri. Am trecut pe Tumblr + Humor API, folosite în paralel, ca
> bot-ul să nu depindă complet de un singur furnizor.

## Cum funcționează

1. `meme_bot.py` interoghează **ambele surse** în fiecare rulare:
   - **Tumblr**: postările cu tag-uri configurabile (implicit: `memes`),
     din tot Tumblr (nu doar dintr-un blog anume) — necesită doar un API
     key (fără login de utilizator).
   - **Humor API**: baza dedicată de meme-uri (peste 300.000), filtrată
     după un rating minim — necesită un API key gratuit.
   Fiecare sursă e opțională independent — dacă lipsește cheia uneia,
   bot-ul continuă cu cealaltă, fără să pice.
2. Filtrează postările: elimină conținut care nu e postare-foto directă,
   cele sub pragul de scor configurat (per sursă — vezi mai jos), și
   cele deja postate sau eșuate anterior (evidența e ținută în
   `posted_ids.json`).
3. Combină rezultatele celor două surse **alternând între ele** (nu le
   amestecă după un scor comun — notele Tumblr și rating-ul Humor API
   sunt pe scale diferite, deci nu sunt comparabile direct).
4. Postează imaginea câștigătoare pe Instagram prin Graph API (Content
   Publishing API), cu un caption care include titlul și creditul sursei
   ("Via Tumblr" / "Via Humor API").
5. Actualizează `posted_ids.json` și îl comite automat înapoi în repo,
   ca să persiste între rulările (efemere) ale GitHub Actions.
6. Workflow-ul GitHub Actions rulează scriptul la un interval fix
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
2. Bifează permisiunile: `instagram_business_basic`,
   `instagram_business_content_publish`,
   `pages_show_list`, `pages_read_engagement`, `business_management`.
   (Numele vechi, `instagram_basic` și `instagram_content_publish`, au
   fost înlocuite oficial de Meta pe 27 ianuarie 2025 — dacă le vezi pe
   cele vechi bifate undeva dintr-un tutorial, nu mai funcționează
   pentru publicare, doar cele noi.)
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

### 5. API key Tumblr

1. Cont Tumblr (dacă nu ai deja) → https://www.tumblr.com
2. Mergi pe https://www.tumblr.com/oauth/apps
3. **Register a new application**, completezi formularul (nume, scurtă
   descriere, URL — poți pune orice, ex. `https://github.com`).
4. După înregistrare, primești un **OAuth Consumer Key** — acesta e
   `TUMBLR_API_KEY`. (Nu ai nevoie de Consumer Secret pentru citire
   publică.)

### 6. API key Humor API

1. Mergi pe https://humorapi.com și creează un cont (dacă nu ai deja).
2. Din contul tău, generezi un **API key** — apare direct în dashboard,
   fără review manual.
3. Copiezi cheia — asta e `HUMOR_API_KEY`.

### 7. (Opțional) Postare pe Facebook, cu poze Picsum

Pe lângă Instagram, bot-ul poate posta opțional și pe o Pagină de
Facebook — flux complet separat, cu poze reale de la Picsum Photos
(nu meme-uri). Dacă nu vrei asta, sari peste acest pas — bot-ul
funcționează normal doar cu Instagram.

1. Aplicația ta Meta trebuie să aibă și cazul de utilizare **"Manage
   everything on your Page"** (Pages API) — diferit de "Facebook Login
   for Business". Din **Cazuri de utilizare → Add use cases**, îl
   adaugi dacă nu-l ai deja.
2. După ce l-ai adăugat, **Customize** lângă el → permisiunea
   `pages_manage_posts` ar trebui să apară/să fie adăugată automat.
3. În **Graph API Explorer**, regenerezi tokenul de **User Token**,
   bifând de data asta și `pages_manage_posts`, pe lângă toate
   celelalte permisiuni de la pasul 3.
4. Faci din nou schimbul pentru token de lungă durată (pasul 4).
5. Cu noul token de utilizator, scrii în Graph API Explorer:
   ```
   me/accounts
   ```
   **Submit**. Lângă numele Paginii tale, cauți câmpul `access_token`
   — **e diferit de tokenul de utilizator**, e specific Paginii.
   Copiază-l — acesta e `FB_PAGE_ACCESS_TOKEN`.
6. `FB_PAGE_ID` e ID-ul Paginii (același pe care l-ai obținut la pasul
   3, din `me/accounts`).

### 8. Adăugarea secretelor în GitHub

În repo → **Settings → Secrets and variables → Actions → New
repository secret**:

| Nume | Valoare |
|---|---|
| `IG_USER_ID` | ID-ul obținut la pasul 3 |
| `IG_ACCESS_TOKEN` | token-ul de lungă durată de la pasul 4 |
| `TUMBLR_API_KEY` | Consumer Key-ul de la pasul 5 |
| `HUMOR_API_KEY` | API key-ul de la pasul 6 |
| `FB_PAGE_ID` | (opțional) ID-ul Paginii, de la pasul 7 |
| `FB_PAGE_ACCESS_TOKEN` | (opțional) token-ul de Pagină, de la pasul 7 |

Ai nevoie de **cel puțin una** din `TUMBLR_API_KEY` / `HUMOR_API_KEY`
ca bot-ul să pornească — dar recomand ambele, exact ca să existe
redundanță dacă una din surse pică vreodată. `FB_PAGE_ID` /
`FB_PAGE_ACCESS_TOKEN` sunt complet opționale — fără ele, bot-ul
postează doar pe Instagram.

Opțional, în **Settings → Secrets and variables → Actions → Variables**
(nu sunt secrete, doar configurare, cu valori implicite dacă lipsesc):

| Nume | Exemplu | Implicit dacă lipsește |
|---|---|---|
| `TUMBLR_TAGS` | `memes,funny,wholesome` | `memes` |
| `MIN_NOTES_TUMBLR` | `3` | `1` |
| `HUMOR_API_KEYWORDS` | `cats,work` | gol (fără filtrare) |
| `MIN_RATING_HUMORAPI` | `8` | `7` (scala 0-10) |
| `POST_LIMIT_PER_RUN` | `1` | `1` |
| `FB_POST_LIMIT_PER_RUN` | `1` | `1` |
| `PICSUM_PAGES_PER_RUN` | `3` | `2` |
| `MAX_ATTEMPTS_PER_RUN` | `15` | `10` |

### 9. Pune fișierele în repo

Adaugă toate fișierele livrate (inclusiv `.github/workflows/meme_bot.yml`
și `posted_ids.json`) în repo și fă push. GitHub Actions detectează
automat workflow-ul din `.github/workflows/`.

---

## Ce rulează complet automat, fără intervenția ta

După setup-ul de mai sus:

- Workflow-ul pornește singur, conform programului `cron` (implicit la
  fiecare 6 ore — editabil în `.github/workflows/meme_bot.yml`).
- Scriptul verifică Tumblr și Humor API, alege cea mai potrivită postare
  nouă, o publică pe Instagram și actualizează `posted_ids.json`.
- Modificarea e comisă automat înapoi în repo — nu trebuie să faci
  nimic manual.
- Poți declanșa și o rulare manuală oricând din tab-ul **Actions** →
  **Meme Bot** → **Run workflow** (util pentru testare).

Singurul lucru care necesită intervenție periodică e token-ul de
Instagram (nici cheia Tumblr, nici cheia Humor API nu expiră).

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

- **Drepturi de autor**: bot-ul include creditul sursei generic ("Via
  Tumblr" / "Via Humor API"), fără atribuire individuală pe autor —
  redistribuirea conținutului altora poate implica probleme de
  drepturi de autor sau poate încălca termenii platformelor implicate,
  indiferent de credit — verifică termenii tuturor platformelor, mai
  ales dacă intenționezi să rulezi bot-ul la scară mare.
- **Filtrare NSFW pe Tumblr**: filtrul folosit (`is_nsfw`) e o
  aproximare — Tumblr nu expune un flag la fel de fiabil ca cel de pe
  Reddit/Imgur pentru conținutul individual dintr-un tag. Merită
  monitorizat manual din când în când, mai ales la început.
- **Feed-ul Tumblr `/tagged` e cronologic, nu după popularitate**:
  confirmat cu date reale — postările proaspete au de obicei 0-3 note,
  nu mii. `MIN_NOTES_TUMBLR` filtrează doar spam-ul evident, nu
  selectează conținut "viral"; calitatea vine mai mult din alegerea
  tag-urilor decât din prag.
- **Limitări Instagram**: Graph API cere ca imaginea să respecte un
  anumit raport de aspect (~4:5 până la 1.91:1); imaginile care nu se
  încadrează vor eșua la publicare — scriptul le marchează ca eșuate
  (`failed`) și trece la următorul candidat, ca să nu reîncerce la
  infinit aceeași postare.
- **`TUMBLR_FETCH_LIMIT`**: câte postări se cer per tag Tumblr, per rulare
  (implicit 20) — crește dacă vrei un bazin mai mare de candidați.
- **`HUMOR_API_COUNT`**: câte apeluri separate se fac către Humor API per
  rulare (implicit 2). Cota gratuită confirmată e **10 cereri/zi** — cu
  cron-ul implicit la 6 ore (4 rulări/zi), 2 per rulare înseamnă 8/zi,
  sub cotă. Dacă o depășești, primești `402 Payment Required`. Verifică
  pe humorapi.com/dashboard cota ta reală înainte să crești valoarea.

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
