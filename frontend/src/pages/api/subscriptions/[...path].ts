import { createApiProxy } from "../../../lib/server/proxy";

export const { GET, POST, PUT, DELETE, PATCH } = createApiProxy({
    name: "subscriptions",
    // PayPal posts to /webhook with no session at all; it authenticates by
    // signature, which the backend verifies.
    skipAuthPaths: ["webhook"],
});
