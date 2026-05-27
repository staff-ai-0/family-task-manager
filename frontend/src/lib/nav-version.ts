// Evaluated once at Node.js module load (server startup).
// Changes on every deploy/restart. ES module cache guarantees
// BottomNav and Layout receive the same value within a process.
export const NAV_VERSION = Date.now().toString(36);
