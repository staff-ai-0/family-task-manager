import { createApiProxy } from "../../../lib/server/proxy";

export const { GET, POST, PUT, DELETE, PATCH } = createApiProxy({ name: "analytics" });
