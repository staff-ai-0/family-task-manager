import { createApiProxy } from "../../../lib/server/proxy";

// Distinct from api/assignments/complete.ts, which 302-redirects to the
// dashboard: Quest Mode needs the backend's JSON back to animate the pet.
export const { GET, POST, PUT, DELETE, PATCH } = createApiProxy({ name: "task-assignments" });
