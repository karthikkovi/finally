# FinAlly frontend

Next.js (App Router, TypeScript, Tailwind v4) built as a static export and served by FastAPI.

```bash
npm install
npm run dev        # http://localhost:3000; /api/* (incl. SSE) proxied to BACKEND_URL (default http://localhost:8000)
npm run build      # static export to out/
npm test           # Vitest + React Testing Library
npm run lint
npm run typecheck
```

- `components/Workstation.tsx` wires everything: REST data (`lib/api.ts`), the SSE stream (`hooks/usePriceStream.ts`),
  and live revaluation of positions (`lib/portfolio.ts`).
- Charts: Lightweight Charts (`components/charts/TimeSeriesChart.tsx`), SVG sparklines, and a squarified treemap
  (`lib/treemap.ts`, `components/Heatmap.tsx`).
- The `data-testid`s the E2E suite relies on are listed in `planning/TEAM.md`.
