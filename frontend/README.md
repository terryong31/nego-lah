# Nego-Lah Frontend (Nuxt 4 SPA)

The client application for **Nego-Lah**, built with **Nuxt 4** in Single Page Application mode (`ssr: false`) and deployed to **Cloudflare Pages**.

---

## 1. Architecture Highlights

- **Single Page Application (`ssr: false`):** Pre-rendered static shell with dynamic client-side hydration, optimized for edge delivery via Cloudflare CDN.
- **UI & Design System:** Built with **Nuxt UI** (`@nuxt/ui`) components and styled with **TailwindCSS v4**, supporting dark/light mode and accessible color contrast.
- **Trilingual Localization:** Trilingual message catalogues (`en`, `ms`, `zh`) supporting full interface internationalization and currency formatting.
- **Universal Turnstile Bot Defense:** Every session maintains active Cloudflare Turnstile verification via `useTurnstileToken()`.
- **Server-Side Sessions:** The backend brokers every Supabase auth call and issues an opaque, httpOnly session cookie — no access or refresh token is ever readable by JavaScript, so XSS has nothing to steal (SPEC-093). Realtime rides the same authenticated stream (SPEC-094).

---

## 2. Directory Structure

```text
frontend/
├── app/
│   ├── assets/       # Global CSS and Tailwind v4 theme configuration
│   ├── components/   # Modular Vue 3 components (hero, admin, chat, items)
│   ├── composables/  # Reactive hooks (useApi, useTurnstileToken, useNotifications)
│   ├── layouts/      # Root layout wrappers (default, admin)
│   ├── locales/      # i18n translation JSON dictionaries (en, ms, zh)
│   ├── pages/        # File-based routing (chat, items, orders, console)
│   └── stores/       # Pinia state stores
├── public/           # Static assets, PWA icons, favicon
├── tests/            # Vitest unit and component tests
├── nuxt.config.ts    # Nuxt 4 configuration & runtime env mappings
└── wrangler.toml     # Cloudflare Pages build & deployment configuration
```

---

## 3. Development Workflow

```bash
# 1. Install dependencies
bun install

# 2. Start dev server (http://localhost:3000)
bun dev

# 3. Run unit & component tests
bun run test

# 4. Typecheck Vue components
bun run typecheck

# 5. Lint codebase
bun run lint

# 6. Generate production static SPA
bun run generate
```

For platform-wide architecture details, refer to [`docs/architecture/README.md`](../docs/architecture/README.md).
