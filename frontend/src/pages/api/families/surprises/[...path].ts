import { createApiProxy } from "../../../../lib/server/proxy";

// UX-D4b: the surprise jar (GET/POST /api/families/surprises, DELETE
// /api/families/surprises/{id}). A rest route matches the bare path too.
export const { GET, POST, DELETE } = createApiProxy({ name: "families-surprises" });
