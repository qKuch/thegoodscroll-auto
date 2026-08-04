# Meme Bot pentru Instagram (Reddit → Instagram, prin GitHub Actions)

Bot care preia automat cele mai populare postări de tip imagine din
subreddit-uri alese de tine și le postează pe un cont Instagram
Business/Creator, cu credit pentru autorul original. Rulează integral pe
GitHub Actions — fără server propriu, fără cron local.

## Cum funcționează

1. `meme_bot.py` interoghează endpoint-ul public JSON al Reddit
   (`/r/<subreddit>/hot.json`) pentru fiecare subreddit din listă — fără
   autentificare.
2. Filtrează postările: elimină cele sub pragul de upvote-uri, cele care
   nu sunt imagini directe (jpg/png), cele NSFW/fixate, și cele deja
   postate sau eșuate anterior (evidența e ținută în `posted_ids.json`).
3. Postează imaginea câștigătoare pe Instagram prin Graph API (Content
   Publishing API), cu un caption care include titlul, `u/autor` și
   subreddit-ul sursă.
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
   "Instagram" în lista de produse, în funcție de interfața curentă).
3. Adaugă și **Facebook Login for Business**, necesar pentru a genera
   token-ul de acces.

### 3. Obținerea `IG_USER_ID`

1. Din **Graph API Explorer**
   (https://developers.facebook.com/tools/explorer/), selectează
   aplicația ta.
2. Generează un token de test cu permisiunile: `instagram_basic`,
   `instagram_content_publish`, `pages_show_list`,
   `pages_read_engagement`.
3. Rulează `GET /me/accounts` — obții ID-ul Paginii de Facebook
   conectate.
4. Rulează `GET /{page-id}?fields=instagram_business_account` —
   răspunsul conține `IG_USER_ID`.

### 4. Obținerea unui token de acces de lungă durată

Token-ul din Graph API Explorer e valabil doar 1-2 ore. Trebuie
schimbat cu unul de lungă durată (~60 zile):

```
GET https://graph.facebook.com/v21.0/oauth/access_token
    ?grant_type=fb_exchange_token
    &client_id=<APP_ID>
    &client_secret=<APP_SECRET>
    &fb_exchange_token=<TOKEN_SCURT_DIN_EXPLORER>
```

Răspunsul conține `access_token`-ul de lungă durată — acesta e
`IG_ACCESS_TOKEN`.

### 5. Adăugarea secretelor în GitHub

În repo → **Settings → Secrets and variables → Actions → New
repository secret**:

| Nume | Valoare |
|---|---|
| `IG_USER_ID` | ID-ul obținut la pasul 3 |
| `IG_ACCESS_TOKEN` | token-ul de lungă durată de la pasul 4 |

Opțional, în **Settings → Secrets and variables → Actions → Variables**
(nu sunt secrete, doar configurare, cu valori implicite dacă lipsesc):

| Nume | Exemplu | Implicit dacă lipsește |
|---|---|---|
| `SUBREDDITS` | `memes,wholesomememes,funny` | `memes,wholesomememes` |
| `MIN_UPVOTES` | `2000` | `1000` |
| `POST_LIMIT_PER_RUN` | `1` | `1` |

### 6. Pune fișierele în repo

Adaugă toate fișierele livrate (inclusiv `.github/workflows/meme_bot.yml`
și `posted_ids.json`) în repo și fă push. GitHub Actions detectează
automat workflow-ul din `.github/workflows/`.

---

## Ce rulează complet automat, fără intervenția ta

După setup-ul de mai sus:

- Workflow-ul pornește singur, conform programului `cron` (implicit la
  fiecare 6 ore — editabil în `.github/workflows/meme_bot.yml`).
- Scriptul verifică subreddit-urile, alege cea mai potrivită postare
  nouă, o publică pe Instagram și actualizează `posted_ids.json`.
- Modificarea e comisă automat înapoi în repo — nu trebuie să faci
  nimic manual.
- Poți declanșa și o rulare manuală oricând din tab-ul **Actions** →
  **Meme Bot** → **Run workflow** (util pentru testare).

Singurul lucru care necesită intervenție periodică e token-ul.

## Reînnoirea token-ului (la ~60 de zile)

Token-ul de lungă durată emis de Meta expiră după aproximativ 60 de
zile — nu există reînnoire automată implicită pentru acest flux.
Înainte de expirare:

1. Repetă schimbul de la pasul 4, folosind **token-ul curent, încă
   valid**, ca `fb_exchange_token` — primești un nou token valabil alte
   60 de zile.
2. Actualizează secretul `IG_ACCESS_TOKEN` din GitHub cu noua valoare.

**Recomandare:** pune-ți un memento recurent (calendar) la ~50 de zile,
ca să nu prinzi token-ul expirat. Dacă token-ul expiră complet, va
trebui reluat fluxul de autentificare de la Graph API Explorer (pașii
3-4).

## Note importante

- **Politica Reddit**: endpoint-ul JSON public nu necesită
  autentificare, dar Reddit limitează cererile automate agresive —
  scriptul trimite un `User-Agent` distinct (configurabil via
  `REDDIT_USER_AGENT`) ca să reducă riscul de `429 Too Many Requests`.
  Pentru robustețe suplimentară pe termen lung, ia în calcul
  înregistrarea unei aplicații Reddit oficiale (OAuth).
- **Drepturi de autor**: bot-ul include mereu creditul sursei
  (`u/autor`, subreddit, link), dar redistribuirea conținutului altora
  poate implica probleme de drepturi de autor sau poate încălca
  termenii Reddit/Instagram, indiferent de credit — verifică termenii
  ambelor platforme, mai ales dacă intenționezi să rulezi bot-ul la
  scară mare.
- **Limitări Instagram**: Graph API cere ca imaginea să respecte un
  anumit raport de aspect (~4:5 până la 1.91:1); imaginile care nu se
  încadrează vor eșua la publicare — scriptul le marchează ca eșuate
  (`failed`) și trece la următorul candidat, ca să nu reîncerce la
  infinit aceeași postare.
- **`FETCH_LIMIT`**: numărul de postări "hot" preluate per subreddit la
  fiecare rulare (implicit 25) — poți crește prin variabila de mediu
  dacă vrei un bazin mai mare de candidați.

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
