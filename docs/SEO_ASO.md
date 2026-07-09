# SEO & ASO — Spanish-first growth playbook

**Market:** Mexico-first, bilingual ES/EN. Default language is Spanish (`lang`
cookie defaults to `es`; Accept-Language fallback is `es`). Spanish organic
search and App Store discovery for family-chore / kids-rewards apps is
near-empty and cheap to win — this doc is the target-keyword + content + ASO
plan behind the technical SEO shipped alongside it.

Canonical origin: `https://family.agent-ia.mx` (see `frontend/src/lib/seo.ts`
`SITE_URL` and `astro.config.mjs` `site`).

---

## 1. What shipped (technical SEO)

| Item | Where |
|------|-------|
| Per-page localized `<title>` + meta description (ES default) | `frontend/src/lib/seo.ts` + each public page |
| Canonical (self-referential, absolute) on every page | `components/meta/Head.astro` |
| `hreflang` `es` / `en` / `x-default` (x-default → ES) | `components/meta/Head.astro` |
| Open Graph + Twitter card (absolute `og:image`, `og:url`, locale) | `components/meta/Head.astro` |
| JSON-LD `Organization` + `WebApplication` on the landing page | `lib/seo.ts` → `index.astro` |
| `/sitemap.xml` (public routes) | `pages/sitemap.xml.ts` |
| `/robots.txt` (allow marketing, disallow app/API, link sitemap) | `pages/robots.txt.ts` |
| Public routes whitelisted for crawlers (no auth bounce) | `middleware.ts` `publicRoutes` |

Locale model: **one URL per page**, language chosen by cookie / Accept-Language
(no `/es/` `/en/` path split). Canonical is self-referential; `es`/`en`
hreflang point at the same URL except the guide pages (`/ayuda` ↔ `/help`),
which are genuinely distinct per-language URLs and cross-reference each other.

### Follow-ups worth doing next
- **Public `/pricing` page.** Today `/pricing/upgrade` 301s to the auth-gated
  `/parent/settings/subscription`, so there is *no* crawlable pricing page.
  A public, Spanish-first pricing page ("precio", "cuánto cuesta", "plan
  gratis") is a high-intent, low-competition win. When built, add it to
  `SITEMAP_ROUTES` and remove `/pricing` from the `robots.txt` `DISALLOW` list.
- **Localized OG images** (`og-es.png` / `og-en.png`) instead of the single
  bilingual `/og.png`.
- **A Spanish blog / `/recursos`** hub for the content topics in §3 — that is
  where the long-tail traffic actually lands.

---

## 2. Target Spanish long-tail keywords

Grouped by intent. Priority = estimated ease × relevance for a Mexican parent
audience. Spanish variants first (primary market), with regional synonyms
because "chores"/"allowance" differ across ES-MX vs ES-ES.

### 2.1 Core category (chores / tasks for kids)
- `tareas para niños` / `tareas del hogar para niños`
- `quehaceres del hogar` / `quehaceres para niños`
- `app de tareas para niños`
- `lista de tareas para niños por edad`
- `responsabilidades para niños según la edad`
- `tabla de tareas para niños` / `tabla de responsabilidades imprimible`
- `organizar tareas de la casa en familia`

### 2.2 Rewards & points economy
- `recompensas para niños` / `sistema de recompensas para niños`
- `premios por buen comportamiento`
- `economía de fichas` (token economy — the clinical/ABA term, high intent)
- `tabla de puntos y premios para niños`
- `motivar a los niños a hacer sus tareas`

### 2.3 Allowance / money (the CASH side — /gigs)
- `domingo para niños` (MX term for allowance)
- `mesada para niños` (LatAm/ES term)
- `cuánto domingo dar según la edad`
- `enseñar a los niños a ahorrar`
- `app de domingo / mesada digital`
- `dinero por tareas extra para adolescentes`

### 2.4 Routines & ADHD (high-empathy, high-conversion)
- `rutinas para niños` / `rutina diaria para niños`
- `rutinas para niños con TDAH`
- `TDAH rutinas y hábitos`
- `tablero de rutinas visual para niños`
- `cómo crear hábitos en niños`

### 2.5 Family budget (the envelope budget module)
- `presupuesto familiar` / `cómo hacer un presupuesto familiar`
- `presupuesto por sobres` (envelope method)
- `app de presupuesto familiar en español`
- `controlar gastos del hogar`
- `finanzas familiares para principiantes`

### 2.6 Long-tail / branded-adjacent
- `alternativa a [apps de tareas] en español`
- `app familiar para tareas y recompensas gratis`
- `app para organizar a la familia con hijos`

> **English keeps a parallel set** (chores app for kids, allowance app,
> reward chart, ADHD routine chart, family budgeting app, envelope budgeting)
> but Spanish is the wedge — competition is thin and the product is ES-native.

---

## 3. Content / blog topics (Spanish-first)

Each maps to a keyword cluster above and should link to `/register`. Write ES
first, translate to EN. Long, evergreen, genuinely useful — these are the pages
that rank and convert.

1. **"Tabla de tareas por edad: qué puede hacer un niño de 3 a 17 años"**
   — the definitive age-appropriate chores chart. Downloadable PDF magnet.
   Targets 2.1 + "según la edad".
2. **"¿Cuánto domingo (o mesada) darle a tu hijo según su edad?"**
   — a table + calculator. Targets 2.3, very high intent.
3. **"Economía de fichas en casa: cómo motivar sin premios de dinero"**
   — points vs. cash; ties directly to the two-currency model. Targets 2.2.
4. **"Rutinas y tareas para niños con TDAH que sí funcionan"**
   — empathy-led, expert-toned. Targets 2.4, low competition, loyal audience.
5. **"Presupuesto familiar por sobres: guía paso a paso (con plantilla)"**
   — envelope method + how the app automates it. Targets 2.5.
6. **"Cómo enseñar a tus hijos a ahorrar con su domingo"**
   — pairs allowance (cash) with the Spend/Save/Share jars. Targets 2.3 + 2.5.
7. **"5 apps para organizar las tareas de la familia (y cuál es gratis)"**
   — comparison / listicle capturing "app de tareas" + "alternativa" searches.
8. **"Puntos y premios vs. dinero: cómo recompensar a tus hijos sin malcriarlos"**
   — reinforces the product's core distinction (points = privileges, gigs = cash).

**On-page pattern for each post:** H1 with the exact keyword phrase; a short
answer in the first paragraph (featured-snippet bait); a table or checklist;
a soft CTA to `/register`; internal links to `/ayuda` and 1–2 sibling posts.

---

## 4. App Store / Play Store ASO fields

Two-currency + bilingual product. Fill the ES (es-MX) locale first; mirror to
en-US. Keep the brand token line consistent with the web (`docs/design-tokens.md`).

### 4.1 App name / title (30 chars, iOS)
- **ES:** `Family Task — Tareas y Premios`
- **EN:** `Family Task — Chores & Rewards`

### 4.2 Subtitle (30 chars, iOS) / short description (80 chars, Play)
- **ES subtitle:** `Tareas, domingo y ahorro`
- **EN subtitle:** `Chores, allowance & saving`
- **ES short (Play):** `Tareas del hogar, puntos y premios para niños, y presupuesto familiar.`
- **EN short (Play):** `Household chores, points and rewards for kids, and family budgeting.`

### 4.3 Keyword field (iOS, 100 chars, comma-separated, no spaces)
Do **not** repeat words already in the title/subtitle. Singular > plural (iOS
auto-pluralizes). No brand names of competitors.
```
tarea,niños,quehacer,recompensa,puntos,mesada,rutina,hogar,familia,ahorro,presupuesto,hijos,premio,tdah
```

### 4.4 Long description (opening lines matter most)

**ES (es-MX):**
> Family Task Manager convierte las tareas del hogar en un juego para toda la
> familia. Asigna quehaceres, premia a tus hijos con puntos que canjean por
> recompensas, y paga trabajos extra ("gigs") con dinero real. Además, lleva
> el presupuesto familiar por sobres — todo en una sola app, en español.
>
> • Tareas automáticas con reparto semanal justo
> • Puntos por tareas → premios y privilegios (tiempo de pantalla, salidas…)
> • Domingo/mesada digital: paga los gigs en efectivo y enséñales a ahorrar
>   con frascos de Gastar / Ahorrar / Compartir
> • Presupuesto familiar y escáner de recibos con IA
> • Roles para papás, adolescentes y niños · Bilingüe español/inglés

**EN (en-US):**
> Family Task Manager turns household chores into a game the whole family
> plays. Assign chores, reward kids with points they redeem for rewards, and
> pay for extra jobs ("gigs") with real cash. Plus an envelope-style family
> budget — all in one app.
>
> • Automated chores with a fair weekly shuffle
> • Points for chores → rewards & privileges (screen time, outings…)
> • Digital allowance: pay gigs in cash and teach saving with Spend / Save /
>   Share jars
> • Family budgeting and AI receipt scanning
> • Roles for parents, teens, and kids · Bilingual Spanish/English

### 4.5 Category & audience
- Primary category: **Lifestyle** (alt: Productivity).
- Secondary: **Education** (age-appropriate chores + money habits).
- Content rating: 4+ / Everyone. Note parental control + child accounts.

### 4.6 Screenshot caption ideas (ES)
1. `Tareas que se reparten solas cada semana`
2. `Puntos por cada tarea → premios que tú eliges`
3. `Gigs: paga trabajos extra en efectivo`
4. `Ahorro con frascos: Gastar · Ahorrar · Compartir`
5. `Presupuesto familiar, sin hojas de cálculo`

### 4.7 ASO hygiene
- Localize **every** store field for es-MX (not just Spanish-from-Spain).
- Keep the two-currency wording honest: **points = privileges, gigs = cash** —
  never imply points convert to money (it's a product constraint and a review
  risk).
- Ask happy families for ratings after a completed-gig approval (peak-happiness
  moment). Reply to ES reviews in Spanish.
- Re-test keywords quarterly; "domingo" (MX) vs "mesada" (LatAm) and "TDAH"
  clusters shift seasonally (back-to-school = August–September in MX).
