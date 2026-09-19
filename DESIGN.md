# T1 Energy — Style Reference

> Factory floor blueprint on warm vellum — a quiet, monochromatic stage where industrial scale and whisper-light typography carry the entire brand.

**Theme:** light

**Источник:** https://styles.refero.design/style/e79b761d-f476-4c5d-8943-e31a58664e4d
Приложен пользователем 19.09.2026 как визуальная система лендинга (дорожка V в `TODO.md`).

T1 Energy speaks the visual language of precision manufacturing: a warm cream canvas, charcoal typography rendered in whisper-light weight, and rounded geometry that softens industrial subject matter. The interface is nearly colorless by design — every element earns its presence through scale, spacing, and shape rather than hue. Navigation floats as a dark pill against the pale surface, imagery uses dramatically rounded 80px corners that echo engineered curves, and content sections breathe with generous 48px gaps. The overall feel is that of a technical specification sheet rendered as a website — precise, confident, and unadorned.

## Tokens — Colors

| Name | Value | Token | Role |
|------|-------|-------|------|
| Vellum | `#f0efe9` | `--color-vellum` | Page canvas, section backgrounds — the warm off-white that defines the entire surface treatment |
| Paper White | `#ffffff` | `--color-paper-white` | Hairline borders, dividers, input outlines, and card edges on light surfaces. Do not promote it to the primary CTA color |
| Carbon Warm | `#322d2a` | `--color-carbon-warm` | Dark borders and separators for elevated surfaces and inverted UI. Do not promote it to the primary CTA color |
| Onyx Depth | `#0f0e12` | `--color-onyx-depth` | Footer surface, deepest elevation layer, darkest UI containers |
| Mercury | `#8b8b8b` | `--color-mercury` | Muted secondary text, disabled states, subtle surface layering |
| Полосы этапов | `--band-1` … `--band-8` | см. «Подложки этапов» | Фон секции во всю ширину окна, свой оттенок на каждый из восьми этапов |
| Pure Black | `#000000` | `--color-pure-black` | SVG icon fills, monochrome graphic elements only — never used for text or backgrounds |

## Tokens — Typography

### T1 Sans

The sole typeface across all surfaces. Weight 300 is used at 52px for hero and section display headlines — an anti-convention choice that makes industrial copy feel architectural rather than assertive. Weight 400 at 14px handles body, labels, and navigation. The custom geometric construction carries a technical-instrument quality that system sans-serifs cannot replicate. The 1.0 line-height on display creates tight headline blocks; the 1.3 on body gives reading comfort.

- **Token:** `--font-t1-sans`
- **Substitute:** Inter or Söhne
- **Weights:** 300, 400
- **Sizes:** 14px, 52px
- **Line height:** 1.00 (display), 1.30 (body)
- **Letter spacing:** 0.01em universally (~0.52px at 52px, ~0.14px at 14px) — barely open, just enough to prevent the light weight from feeling cramped
- **OpenType features:** No special features detected; rely on default contextual alternates

### Type Scale

| Role | Size | Line Height | Letter Spacing | Token |
|------|------|-------------|----------------|-------|
| label | 12px | 1.3 | 0.12px | `--text-label` |
| body-sm | 14px | 1.3 | 0.14px | `--text-body-sm` |
| body | 16px | 1.4 | 0.16px | `--text-body` |
| subheading | 22px | 1.3 | 0.22px | `--text-subheading` |
| heading | 32px | 1.2 | 0.32px | `--text-heading` |
| display | 52px | 1 | 0.52px | `--text-display` |

## Tokens — Spacing & Shapes

**Base unit:** 4px · **Density:** comfortable

### Spacing Scale

| Name | Value | Token |
|------|-------|-------|
| 4 | 4px | `--spacing-4` |
| 8 | 8px | `--spacing-8` |
| 12 | 12px | `--spacing-12` |
| 16 | 16px | `--spacing-16` |
| 24 | 24px | `--spacing-24` |
| 36 | 36px | `--spacing-36` |
| 48 | 48px | `--spacing-48` |
| 60 | 60px | `--spacing-60` |
| 96 | 96px | `--spacing-96` |
| 120 | 120px | `--spacing-120` |

### Border Radius

| Element | Value |
|---------|-------|
| nav | 16px |
| body | 12px |
| cards | 80px |
| pills | 100px |
| small | 8px |
| buttons | 16px |

### Layout

- **Page max-width:** 1200px
- **Section gap:** 48px
- **Card padding:** 22px
- **Element gap:** 8px

## Components

### Pill Navigation Bar

**Role:** Primary site navigation — floats as a dark horizontal pill anchored top-right

Dark Carbon Warm (#322d2a) background, 16px border-radius, 36px vertical padding, 24px horizontal padding. White (#ffffff) link text at 14px weight 400, separated by 24px gaps. Logo mark appears to the left within the same pill or adjacent. Sits over page content with no visible shadow — the contrast difference alone separates it from the vellum canvas.

### Logo Mark

**Role:** Brand identifier in navigation

Geometric 'T1' wordmark in white when on dark navigation surface. Simple constructed letterforms with the '1' sharing the 'T' crossbar. No tagline, no decorative element.

### Filled Primary Button

**Role:** Primary action trigger

Carbon Warm (#322d2a) background, white text at 14px weight 400, 18px vertical / 22px horizontal padding, 100px border-radius (full pill). No border, no shadow. The pill shape and dark fill make it the highest-weight interactive element on any page.

### Ghost Outlined Button

**Role:** Secondary action trigger

Transparent background, 1px Carbon Warm (#322d2a) border, Carbon Warm text at 14px weight 400, 18px vertical / 22px horizontal padding, 100px border-radius (full pill). The outlined pill mirrors the filled button's geometry, differing only in fill — the two are a matched pair.

### Section Label

**Role:** Tiny uppercase section identifier (e.g. 'MISSION', 'TECHNOLOGY', 'CASE STUDY')

A small solid square (4px × 4px) in Carbon Warm precedes the label text. Label rendered at ~11–12px weight 400, uppercase, letter-spacing ~0.12em, Carbon Warm color. The square indicator is a signature device — it replaces the conventional dot or icon and gives the labels a machined, dial-like quality.

### Display Headline

**Role:** Hero and section-level headlines

T1 Sans weight 300, 52px, line-height 1.0, letter-spacing 0.52px, Carbon Warm color. The ultra-light weight is the single most distinctive typographic choice on the site — it makes large headlines feel like etched specifications rather than shouted declarations.

### Case Study Card

**Role:** Compact overlay card on hero image

Carbon Warm (#322d2a) dark surface, 12px border-radius, ~16px padding. Contains a label in white at 12px, a short white headline at 14px weight 400, and a small thumbnail image on the right side. The dark card on a photographic background creates a film-still caption effect.

### Image Card

**Role:** Full-bleed image containers in content sections

Image fills the container edge-to-edge. Container border-radius is 80px — the most dramatic radius on the site, making rectangular photos feel almost circular. No caption, no border, no shadow; the image is the entire content.

### Accordion Item

**Role:** Expandable breakdown

Full-width row with Carbon Warm text label at ~18–22px weight 400 on the left, circular expand/collapse icon button on the right. The icon button is 40px diameter, 100px border-radius, Carbon Warm 1px border, white background. Active/expanded item shows a minus (−) icon; collapsed items show a plus (+). Rows are separated by 1px Carbon Warm hairlines. The active item's description text appears in smaller weight below the label.

### Hero Overlay

**Role:** Full-viewport photographic background with text overlay

Full-bleed industrial photograph with a large display headline (52px weight 300, white) positioned bottom-left. A filled primary button sits below the headline. No gradient, no darkening overlay — the text relies on the photographic tonal range for legibility.

### Footer

**Role:** Site footer with darkest surface treatment

Onyx Depth (#0f0e12) background, 30px bottom padding, white text at 14px weight 400. The near-black footer is the only place a dark surface appears at full width, giving the page a definitive terminator.

## Do's and Don'ts

### Do

- Use weight 300 at 52px for all display headlines — the light weight is the brand's typographic signature and should not be replaced by 600/700 bold.
- Set border-radius to 80px on all image containers and 100px on all interactive buttons to maintain the pill-and-orb geometry.
- Use Carbon Warm (#322d2a) for all borders, text, and filled interactive elements — never use pure black #000000 for text or backgrounds.
- Maintain section gaps of 48px and card padding of 22px to preserve the breathing, specification-sheet rhythm.
- Prefix every section label with the 4px solid square indicator in Carbon Warm before the uppercase label text.
- Keep the palette to vellum canvas, white surfaces, and carbon text — the absence of color is the design.
- Set display headline line-height to exactly 1.0 so the large 52px text forms a tight, architectural block.

### Don't

- Do not introduce accent colors, gradients, or decorative hues — the 1% colorfulness is intentional and breaking it will shatter the engineered restraint.
- Do not use pure black (#000000) for text, backgrounds, or borders — always warm it to Carbon Warm (#322d2a) or cool it to Onyx (#0f0e12).
- Do not apply box-shadows to cards, buttons, or navigation — the design relies on flat tonal layering (vellum → white → carbon), not elevation.
- Do not set border-radius below 8px on any container — the system is built on generous rounding, and sharp corners will feel out of place.
- Do not use bold or semibold weights for headlines — the family ships 300 and 400, and the whisper-light display is the whole point.
- Do not add icons, illustrations, or emoji to section labels or body copy — the square indicator and typography carry all visual signaling.
- Do not break the full-bleed image pattern with borders, frames, or padding around photographs.

## Surfaces

| Level | Name | Value | Purpose |
|-------|------|-------|---------|
| 0 | Vellum Canvas | `#f0efe9` | Base page background and the majority of content sections |
| 1 | Paper White | `#ffffff` | Elevated cards, floating panels, content wells above the vellum canvas |
| 2 | Carbon Warm | `#322d2a` | Navigation pill, filled buttons, case study card, footer-adjacent dark surfaces |
| 3 | Onyx Depth | `#0f0e12` | Footer terminator, darkest elevation layer |

## Elevation

The design is deliberately shadowless. All visual hierarchy is achieved through tonal layering (vellum → white → carbon → onyx) and generous spacing, never through drop shadows. This keeps the interface feeling flat, precise, and instrument-like rather than skeuomorphic or app-like.

## Imagery

Photography is full-bleed industrial documentary — factory floors, robotic arms, production lines — presented without overlays, duotones, or color treatment. Images are cropped to fill their containers edge-to-edge with 80px border-radius, making them feel like circular portholes into the manufacturing process. No lifestyle photography, no abstract graphics, no illustrations. Product renders appear as isolated objects on the vellum canvas with no background treatment.

## Layout

Max-width 1200px centered content, with hero sections breaking out to full-bleed. Below the hero, content alternates in single-column stacks and two-column splits (text-left/image-right). Image cards use 80px corner radius and sit side-by-side as a two-column pair. Vertical rhythm is controlled by 48px section gaps with generous internal breathing room. Navigation is a floating dark pill anchored to the top of the viewport, not a full-width bar. No sidebar, no mega-menu, no sticky elements beyond the nav.

## Quick Color Reference

- text: `#322d2a` (Carbon Warm)
- background: `#f0efe9` (Vellum)
- surface: `#ffffff` (Paper White)
- border: `#322d2a`
- accent: none — the system is monochromatic
- primary action: no distinct CTA color

## Signature Design Choices

Three choices define this system more than any other: (1) Weight 300 at 52px for all display headlines — an anti-convention whisper-weight that makes industrial copy feel architectural; (2) The 4px solid square preceding every section label — a machined dial-indicator replacing the conventional bullet or icon; (3) 80px border-radius on all image containers — turning rectangular photographs into soft portholes that contrast with the otherwise flat, technical interface. Together these create a visual language that is simultaneously industrial and gentle, precise and breathable.

## Similar Brands

- **Crusoe Energy** — Same ultra-minimal monochromatic approach with warm neutrals, large whisper-light headlines, and full-bleed industrial photography
- **Commonwealth Fusion Systems** — Deep-tech manufacturing brand using a nearly colorless palette, dark pill navigation, and generous rounded image containers
- **Form Energy** — Clean industrial energy company with flat tonal layering, no shadows, and dramatic corner radii on media containers
- **Hadrian** — American advanced-manufacturing brand using warm off-white canvas, charcoal text, and pill-shaped navigation as the sole chromatic gesture
- **Sila** — Battery technology company with the same specification-sheet aesthetic — flat surfaces, monospaced-feeling geometry, and full-bleed factory photography

## Quick Start — CSS Custom Properties

```css
:root {
  /* Colors */
  --color-vellum: #f0efe9;
  --color-paper-white: #ffffff;
  --color-carbon-warm: #322d2a;
  --color-onyx-depth: #0f0e12;
  --color-mercury: #8b8b8b;
  --color-pure-black: #000000;

  /* Typography — Font Families */
  --font-t1-sans: 'T1 Sans', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;

  /* Typography — Scale */
  --text-label: 12px;
  --leading-label: 1.3;
  --tracking-label: 0.12px;
  --text-body-sm: 14px;
  --leading-body-sm: 1.3;
  --tracking-body-sm: 0.14px;
  --text-body: 16px;
  --leading-body: 1.4;
  --tracking-body: 0.16px;
  --text-subheading: 22px;
  --leading-subheading: 1.3;
  --tracking-subheading: 0.22px;
  --text-heading: 32px;
  --leading-heading: 1.2;
  --tracking-heading: 0.32px;
  --text-display: 52px;
  --leading-display: 1;
  --tracking-display: 0.52px;

  /* Typography — Weights */
  --font-weight-light: 300;
  --font-weight-regular: 400;

  /* Spacing */
  --spacing-unit: 4px;
  --spacing-4: 4px;
  --spacing-8: 8px;
  --spacing-12: 12px;
  --spacing-16: 16px;
  --spacing-24: 24px;
  --spacing-36: 36px;
  --spacing-48: 48px;
  --spacing-60: 60px;
  --spacing-96: 96px;
  --spacing-120: 120px;

  /* Layout */
  --page-max-width: 1200px;
  --section-gap: 48px;
  --card-padding: 22px;
  --element-gap: 8px;

  /* Border Radius */
  --radius-lg: 8px;
  --radius-xl: 12px;
  --radius-2xl: 16px;
  --radius-full: 80px;
  --radius-full-2: 100px;

  /* Named Radii */
  --radius-nav: 16px;
  --radius-body: 12px;
  --radius-cards: 80px;
  --radius-pills: 100px;
  --radius-small: 8px;
  --radius-buttons: 16px;

  /* Surfaces */
  --surface-vellum-canvas: #f0efe9;
  --surface-paper-white: #ffffff;
  --surface-carbon-warm: #322d2a;
  --surface-onyx-depth: #0f0e12;

  /* Подложки этапов — фон секции во всю ширину окна */
  --band-0: #f0efe9;
  --band-1: #f2ebd7;
  --band-2: #d7e4f2;
  --band-3: #f2d7e0;
  --band-4: #e2d7f2;
  --band-5: #d7edf2;
  --band-6: #dbf2d7;
  --band-7: #f2e2d7;
  --band-8: #d7f2eb;

  /* Парные волосяные линии: рамки карточек на своей полосе */
  --band-line-0: #d6d3c9;
  --band-line-1: #d0cab9;
  --band-line-2: #b9c4d0;
  --band-line-3: #d0b9c1;
  --band-line-4: #c2b9d0;
  --band-line-5: #b9ccd0;
  --band-line-6: #bcd0b9;
  --band-line-7: #d0c2b9;
  --band-line-8: #b9d0ca;

  --band-seam: rgba(50, 45, 42, 0.1);
}
```

## Подложки этапов

Восемь этапов конвейера получают восемь пастельных подложек. Порядок подобран так, чтобы любые
две соседние полосы отличались заведомо заметно (расстояние в RGB не ниже 24), а светлота у всех
восьми оставалась почти одинаковой — страница не скачет от тёмного к светлому при прокрутке.

| Этап | Полоса | Токен | Hex | Контраст к Carbon Warm | Контраст к `--muted` | Отрыв Paper White |
|------|--------|-------|-----|------------------------|----------------------|-------------------|
| 0 Условия | нейтральная | `--band-0` | `#f0efe9` | 11.80 | 6.34 | 1.15 |
| 1 Состояние | песочная | `--band-1` | `#f2ebd7` | 11.42 | 6.13 | 1.19 |
| 2 Доверие к данным | голубая | `--band-2` | `#d7e4f2` | 10.53 | 5.66 | 1.29 |
| 3 Прогноз | розоватая | `--band-3` | `#f2d7e0` | 10.08 | 5.41 | 1.35 |
| 4 Кандидаты | лавандовая | `--band-4` | `#e2d7f2` | 9.87 | 5.30 | 1.38 |
| 5 Gate | небесная | `--band-5` | `#d7edf2` | 11.19 | 6.01 | 1.21 |
| 6 Агенты | шалфейная | `--band-6` | `#dbf2d7` | 11.46 | 6.15 | 1.19 |
| 7 Выбор | глиняная | `--band-7` | `#f2e2d7` | 10.77 | 5.78 | 1.26 |
| 8 Решение | мятная | `--band-8` | `#d7f2eb` | 11.52 | 6.19 | 1.18 |

Все восемь проходят WCAG AA с запасом: основной текст 9.87–11.52 при пороге 4.5, приглушённый
текст 5.30–6.19. Ради этого `--muted` углублён с `#6f6b66` до `#5a564e`, а `--unknown` с
`#7a5514` до `#6a4a11`: прежние значения на самых насыщенных полосах падали ниже 4.5.

Граница между полосами — резкая, плюс волосяная линия `--band-seam` (10% Carbon Warm). Мягкая
растяжка отвергнута: пользователь просил чёткое разделение, а градиент в пастельной гамме читается
как дефект печати, а не как решение.

## Применение в этом проекте — отступления и их причины

Система описывает промо-сайт производственной компании; у нас — рабочий экран советчика оператора
НПЗ. Четыре отступления сделаны осознанно и должны сохраняться при любых аудитах.

**Различие бейджей происхождения — начертанием, а не цветом.** Палитра монохромная, поэтому
`given` / `derived` / `measured` / `scenario` / `open` различаются толщиной и стилем рамки
(сплошная 2px, сплошная 1px, двойная 3px, пунктир, точки). Это работает и в чистом монохроме,
и на чёрно-белой печати.

**Статусный цвет для нарушений — узкое функциональное исключение.** В интерфейсе оператора
«нарушено» обязано читаться мгновенно, поэтому отказ и предупреждение несут приглушённый тёплый
оттенок. Смысл продублирован начертанием, а не передан цветом в одиночку.

**Номер этапа в левой рейке несёт статус цветом — четвёртое узкое исключение.** Оператор должен
читать ход прогона одним взглядом по боковой панели, не разворачивая этапы. Поэтому цифры 0–8
красятся уже существующими токенами: пройден `--pass` `#2f5d4f` (7.50 к Paper White), отказ
`--fail` `#8c3322` (8.04), идёт `--unknown` `#6a4a11` (8.08), не начат `--muted` `#5a564e` (7.30).
Новых цветов не заведено: это те же токены, которыми покрашены проверки Gate и вердикты. На
активной тёмной пилюле те же смыслы берут осветлённые версии того же тона (`#a3d4bb` 8.22,
`#f0a693` 6.85, `#b5b0a6` 6.30), иначе контраст падал бы до 1.7 и текущий этап был бы нечитаем;
состояние «идёт» на пилюле берёт янтарь логотипа `#c8761a` (3.93 при пороге 3:1 для крупного
жирного текста 20px/700).

Смысл нигде не передан цветом в одиночку: пройденный держит вес 700, не начатый падает до веса
400 и 55% непрозрачности, отказ несёт подчёркивание 2px, идущий дышит непрозрачностью с тактом
1800 мс. Все четыре состояния различимы при цветовой слепоте и на чёрно-белой печати. Контурное
(«полое») начертание цифр было опробовано и отвергнуто: на кегле 20px тонкий штрих расплывается
и читается хуже сплошной цифры. Символьные пометки `✓ → ·` убраны — статус читает сама цифра,
а для скринридера состояние дублируется текстом в `.sr-only`.

**Левая рейка появляется только после запуска прогона.** До старта панели нет вовсе, а экран
условий занимает всю ширину: показывать ход прогона, которого ещё не было, нечем. При старте
панель выезжает `translateX(-100%) → 0` за 300 мс, и тем же тактом едет левый отступ контента,
поэтому раскладка не прыгает. Панель остаётся `position: fixed` у левого края и отцентрована по
вертикали окна. При `prefers-reduced-motion` движение снимается, панель просто появляется.

**Фотографий нет, поэтому радиус 80px применён к крупным карточкам-контейнерам.** Промышленной
съёмки в проекте нет и не будет: всё содержимое — числа, таблицы и JSON. Геометрия системы
сохраняется на контейнерах.

**Ограничение ширины 1200px снято: страница занимает всю ширину окна.** Система описывает
промо-сайт, где колонка по центру помогает чтению. У нас рабочий экран: таблицы Gate, кандидатов
и источников содержат десятки строк и по 4–6 колонок, и на 1200px им доставалось 843px вместо
доступных 1548px на 1920 и 2177px на 2560. Вместо жёсткой колонки — боковые отступы
`--page-gutter: clamp(22px, 2.2vw, 48px)`. Читаемость защищена иначе, по месту: текстовые блоки
(описания этапов, оговорки, limits, подписи) держат меру строки `--measure: 78ch`, а плотные
сетки чисел (`.fields`, `.readouts`) ограничены `--dense-max: 1600px`, чтобы значение не
отрывалось от подписи и бейджа происхождения. Таблицы, JSON-панели и графики берут всю ширину.

**Логотип набран жирным начертанием, а не весом 300.** Правило «вес 300 на дисплейных
заголовках» относится к тексту интерфейса. Логотип — не текст, а знак: буквы `CUTPOINT` имеют ту
же массу штриха, что дуга разрезанной C (19.4% диаметра кольца), иначе знак и слово читаются как
две разные вещи. Это осознанное отступление, при аудите логотип не «чинить» до веса 300.

**Акцентный цвет разрешён ровно в одном месте — в линии реза на логотипе.** Палитра интерфейса
остаётся монохромной: ни один элемент экрана акцент не получает. Линия, вплетённая в слово
`CUTPOINT`, — единственное исключение, и она обязана сохранять контраст не ниже 3:1 и к Vellum,
и к Carbon Warm, потому что логотип живёт на обоих фонах. Кандидаты проверены: медь `#bd6a35`
(3.45 / 3.42), янтарь `#c8761a` (3.01 / 3.93), латунь `#a8801f` (3.16 / 3.74). Для чёрно-белой
печати и гравировки существует монохромная версия, где плетение держится разрывами, а не цветом.

**Цветные подложки этапов — самое крупное отступление от системы, сделано по прямому требованию
пользователя.** Система предписывает единую канву Vellum и запрещает декоративные оттенки. У нас
страница длиной в восемь этапов и около десяти тысяч пикселей прокрутки: на одном фоне этапы
различались только отступами, и место в конвейере терялось. Сначала была собрана шкала из восьми
ступеней самого Vellum — формально это осталось бы монохромом. Пользователь отверг её прямо:
«не оттенки бежевого, можно какие-то пастельные синие, зелёные, вообще разные». Поэтому введены
восемь пастельных подложек (таблица в разделе «Подложки этапов»).

Граница отступления проведена жёстко: **цвет живёт только в подложке секции**. Типографика,
рамки, кнопки, бейджи происхождения, лампы состояний и логотип остаются монохромными — ни один
элемент интерфейса акцент не получает. Подложка — это навигационный слой, а не украшение: она
отвечает на вопрос «где я на длинной странице», и ту же работу дублируют номер этапа, заголовок и
левая рейка, поэтому смысл не передан цветом в одиночку и не теряется при цветовой слепоте или
чёрно-белой печати.

Светлота всех восьми полос выровнена (разброс по яркости 1.17), поэтому текст читается одинаково
везде, а страница не мигает при прокрутке. Карточки остаются Paper White и отрываются от подложки
на 1.18–1.38 — на самых светлых полосах отрыв слабее, поэтому у каждой полосы есть парная
волосяная линия `--band-line-*`, которая держит край карточки видимым. Янтарь логотипа `#c8761a`
стоит на нейтральной полосе `--band-0` в шапке и с цветными полосами не соприкасается.

Неизменным остаётся главное: вес 300 на дисплейных заголовках, квадратная метка раздела,
отсутствие теней, закругления не ниже 8px и монохромная типографика — цвет допущен только как
подложка секции.
