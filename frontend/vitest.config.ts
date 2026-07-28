import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
    resolve: {
        alias: {
            // `astro:middleware` is a virtual module that only exists inside an
            // Astro build. Its `defineMiddleware` is an identity helper, so a
            // one-line stub is enough to import src/middleware.ts in plain Node
            // and drive it with a fake request context. Runtime-only: types
            // still come from the real .astro/types.d.ts reference.
            "astro:middleware": fileURLToPath(
                new URL("./test/stubs/astro-middleware.ts", import.meta.url),
            ),
        },
    },
    test: {
        environment: "node",
        include: ["test/**/*.test.ts"],
    },
});
