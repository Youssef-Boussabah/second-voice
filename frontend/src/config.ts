// Single switch for mock vs real backend. No secrets ever live in the frontend.
const env = import.meta.env;
export const API_URL: string = (env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") || "http://localhost:8000";
export const USE_MOCKS: boolean = (env.VITE_USE_MOCKS ?? "true") !== "false";
export const WS_URL: string = API_URL.replace(/^http/, "ws");
