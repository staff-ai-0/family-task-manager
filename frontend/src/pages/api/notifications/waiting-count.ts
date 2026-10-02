import { createApiProxy } from "../../../lib/server/proxy";

// UX-D4a: the one notifications path browser code asks for (lib/appBadge.ts).
// GET only, and this path only — every other /api/notifications call is made
// server-side during render and needs no browser-facing route.
export const { GET } = createApiProxy({ name: "notifications" });
