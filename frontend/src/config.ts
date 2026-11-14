// Single switch for mock vs real backend. No secrets ever live in the frontend.
const env = import.meta.env;
export const API_URL: string = (env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") || "http://localhost:8000";
// Mocks ONLY when explicitly enabled; the default is the real backend.
export const USE_MOCKS: boolean = env.VITE_USE_MOCKS === "true";
// Reset Demo stays hidden until lane-d ships POST /api/admin/reset-demo (or in mock mode).
export const ENABLE_RESET: boolean = env.VITE_ENABLE_RESET === "true";
export const WS_URL: string = API_URL.replace(/^http/, "ws");
