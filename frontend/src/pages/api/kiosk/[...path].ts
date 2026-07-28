import { createApiProxy } from "../../../lib/server/proxy";

export const { GET, POST, PUT, DELETE, PATCH } = createApiProxy({
    name: "kiosk",
    // /snapshot is gated by a device token in the query string, and a kiosk
    // screen has no user cookies to lift or refresh.
    skipAuthPaths: ["snapshot"],
});
