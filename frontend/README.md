# HomeyAI Frontend Client

The frontend of the HomeyAI Platform is an enterprise-ready dashboard application built with **React**, **Next.js 16 (App Router)**, **TypeScript**, and **Tailwind CSS 4.x**. 

It provides users with interactive property valuation inputs, real-time map visualization of amenities, historical price charts, and an AI chat assistant.

---

## 1. Project Directory Structure

The frontend application uses the Next.js App Router pattern:

```text
frontend/
├── Dockerfile            # Production Docker configuration
├── Dockerfile.dev        # Development Docker configuration
├── package.json          # Node dependencies and npm scripts
├── tsconfig.json         # TypeScript configuration
├── eslint.config.mjs     # ESLint linting rules
└── src/
    ├── app/              # Next.js App Router (Pages, Layouts, and API proxy)
    │   ├── admin/        # Admin control panels (health monitor, data catalog)
    │   ├── analytics/    # District-level historical price analytics
    │   ├── api/          # Server-side endpoints and reverse-proxy handlers
    │   ├── saved-properties/ # User bookmarks & saved calculations
    │   ├── valuation/    # Rate-limited valuation form
    │   ├── valuation-report/ # Detailed valuation visualizer
    │   ├── globals.css   # Main Tailwind CSS entrypoint
    │   ├── layout.tsx    # Root layout with providers
    │   └── page.tsx      # Landing page / Home
    ├── components/       # Reusable UI Components
    │   ├── Map.tsx       # Leaflet-based geospatial maps
    │   ├── Charts.tsx    # Recharts data visualizers
    │   ├── Navbar.tsx    # Application header navigation
    │   └── RequireAuth.tsx # Route guard wrapper checking user roles
    ├── context/          # Application global state
    │   └── AuthContext.tsx # User session, login/registration status, JWT tokens
    └── lib/              # Client utilities
        ├── apiBase.ts    # Determines target base URL for API requests
        └── subscriptionPreview.ts # Logic for subscription mock states
```

---

## 2. Environment Configuration

Create a `.env.local` file in the `frontend` root directory to define local configurations:

```env
# Browser-accessible base URL of the FastAPI backend.
# - In Mode B (Laptop dev with remote DB): Point to the VM's Tailscale or Public IP (e.g. http://100.115.82.10:8000).
# - In Mode C (Full Local dev): Point to localhost (http://localhost:8000).
# - If left empty: Automatically falls back to same-origin routing proxy (/api/...).
NEXT_PUBLIC_API_URL=http://localhost:8000

# The Tailscale or Public IP of the remote VM. 
# Used on the `/admin/health` page to offer helpful reachability tips to team members.
NEXT_PUBLIC_REMOTE_VM_IP=100.115.82.10

# Backend origin server used server-side by the Next.js API route proxy.
# Next.js API routes will proxy calls internally to this origin to bypass CORS.
BACKEND_INTERNAL_ORIGIN=http://localhost:8000
```

### The API Base URL Resolver (`src/lib/apiBase.ts`)
The application resolves the backend API origin dynamically:
1. If `NEXT_PUBLIC_API_URL` is set, calls go directly to that URL.
2. If `NEXT_PUBLIC_API_URL` is set to `localhost` but the browser accesses the site from another host (e.g. via a Tailscale IP), the client automatically switches to a same-origin proxy route (`/api/...`) to prevent the browser from attempting loopback calls.
3. If unset, it routes through the Next.js server proxy at `src/app/api/[[...path]]/route.ts` which forwards headers and cookies to `BACKEND_INTERNAL_ORIGIN`.

---

## 3. Core Integrations

### A. Interactive Map Rendering (Leaflet)
Geospatial rendering is built using `leaflet` and `react-leaflet` to display buildings, MRT routes, and POI markers:
* **Dynamic Import:** Since Leaflet requires direct access to browser global objects (`window`, `document`), map components are loaded dynamically with SSR disabled:
  ```tsx
  import dynamic from "next/dynamic";
  const Map = dynamic(() => import("@/components/Map"), { ssr: false });
  ```
* **PostGIS & GeoJSON:** The Map component binds directly to backend endpoints that return PostGIS data formatted as GeoJSON features (e.g., URA regions and PostGIS building footprints via `/api/geospatial/hdb_buildings`).
* **Interactive Drawing:** Includes `leaflet-draw` and `react-leaflet-draw` in the analytics dashboard. This allows administrators and premium users to draw polygons on the map to run queries like `/api/geospatial/area_amenity_breakdown`.

### B. Analytical Charts (Recharts)
Interactive charts and SHAP machine learning feature-contribution tables are powered by `recharts`:
* Responsive chart wrappers (`ResponsiveContainer`) are used to adapt to grid layouts and different screen sizes.
* Main implementations:
  * **Property Valuation Trends:** Area charts showing historical property resale price movements.
  * **Feature Impact (SHAP):** Bar charts visualizing positive and negative contributions of variables (e.g., floor area, distance to MRT) to the final predicted valuation.
  * **District Breakdowns:** Line charts highlighting comparative average prices across URA regions.

### C. Authentication and State Management (`src/context/AuthContext.tsx`)
* Sessions are handled via JWT tokens stored in `localStorage` under `token`.
* The `AuthContext` exposes `user`, `login()`, `logout()`, `register()`, and `isAuthenticated`.
* **Route Protection:** Route access is managed via the `<RequireAuth>` wrapper component (configured with roles `guest`, `free`, `premium`, and `admin`). If a user doesn't meet the role requirements, they are redirected to `/login` or blocked with a forbidden screen.

---

## 4. Developer Commands

Run these scripts from the `frontend` directory:

| Command | Description |
|---------|-------------|
| `npm run dev` | Start Next.js hot-reloaded development server on [http://localhost:3000](http://localhost:3000) |
| `npm run build` | Compile the application and build optimized production bundle in `.next` |
| `npm run start` | Run the compiled production build locally |
| `npm run lint` | Run ESLint check over all source files |
| `npx tsc --noEmit` | Validate type-safety and run TypeScript compiler diagnostics |
