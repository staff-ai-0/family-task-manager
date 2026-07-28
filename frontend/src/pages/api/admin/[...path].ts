import { createApiProxy } from "../../../lib/server/proxy";

// No authorization of its own on purpose: the middleware already 404s this path
// for non-operators and the backend's require_superadmin re-checks independently.
export const { GET, POST, PUT, DELETE, PATCH } = createApiProxy({ name: "admin" });
