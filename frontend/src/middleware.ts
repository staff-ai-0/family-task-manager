import { defineMiddleware } from "astro:middleware";
import type { User } from "./types/api";

/**
 * Middleware for authentication checks and request logging
 */
export const onRequest = defineMiddleware(async (context, next) => {
    const { url, cookies, redirect, request } = context;
    const path = url.pathname;

    // Log all requests in development
    if (import.meta.env.DEV) {
        console.log(`[${request.method}] ${path}`);
    }

    // CSRF Protection for state-changing requests
    // Check CSRF BEFORE authentication check for all non-GET API requests
    if (request.method !== "GET" && path.startsWith("/api/")) {
        const origin = request.headers.get("origin");
        const host = request.headers.get("host");
        
        // Allow null origin for server-side requests (Astro API routes calling backend)
        // This happens when our own API routes make server-to-server requests
        // We only skip the CSRF check; auth checks below still apply
        if (origin !== null) {
            // In development, allow localhost origins
            if (import.meta.env.DEV) {
                const devOrigins = [
                    `http://${host}`,
                    `https://${host}`,
                    "http://localhost:3000",
                    "http://localhost:3003",
                    "http://127.0.0.1:3000",
                    "http://127.0.0.1:3003"
                ];
                if (!devOrigins.includes(origin)) {
                    console.error(`CSRF violation in dev: origin ${origin} not in allowed list for ${path}`);
                    return new Response(
                        JSON.stringify({ detail: "CSRF validation failed" }),
                        { status: 403, headers: { "Content-Type": "application/json" } }
                    );
                }
            } else {
                // In production, strictly enforce same-origin
                const expectedOrigin = `https://${host}`;
                if (origin !== expectedOrigin) {
                    console.error(`CSRF violation: origin ${origin} does not match ${expectedOrigin}`);
                    return new Response(
                        JSON.stringify({ detail: "CSRF validation failed" }),
                        { status: 403, headers: { "Content-Type": "application/json" } }
                    );
                }
            }
        }
    }

    // Always allow static assets (CSS, JS, images, fonts)
    if (path.startsWith("/_astro/") || path.startsWith("/favicon") || path.match(/\.(css|js|png|svg|ico|woff2?|ttf|otf)$/)) {
        return next();
    }

    // Public routes that don't require authentication
    const publicRoutes = ["/", "/login", "/api/auth/login", "/api/oauth/google", "/api/lang"];
    const isPublicRoute = publicRoutes.some(route => path === route || path.startsWith("/api/translate"));

    if (isPublicRoute) {
        return next();
    }

    // Check authentication for protected routes
    const token = cookies.get("access_token")?.value;
    
    if (!token) {
        // Redirect to login for HTML pages
        if (!path.startsWith("/api/")) {
            return redirect("/login", 302);
        }
        // Return 401 for API routes
        return new Response(
            JSON.stringify({ detail: "Unauthorized" }),
            { status: 401, headers: { "Content-Type": "application/json" } }
        );
    }

    // Verify token is valid by checking with backend for API routes
    // For page routes, we'll let the page components handle token validation
    if (path.startsWith("/api/") && path !== "/api/auth/login") {
        try {
            const apiUrl = process.env.PUBLIC_API_URL ?? "http://localhost:8002";
            const response = await fetch(`${apiUrl}/api/auth/me`, {
                headers: {
                    "Authorization": `Bearer ${token}`,
                },
            });

            if (!response.ok) {
                cookies.delete("access_token", { path: "/" });
                return new Response(
                    JSON.stringify({ detail: "Invalid or expired token" }),
                    { status: 401, headers: { "Content-Type": "application/json" } }
                );
            }

            const user: User = await response.json();
            
            // Attach user to context for use in endpoints
            context.locals.user = user;
            context.locals.token = token;
        } catch (error) {
            console.error("Token validation error:", error);
            cookies.delete("access_token", { path: "/" });
            return new Response(
                JSON.stringify({ detail: "Authentication error" }),
                { status: 500, headers: { "Content-Type": "application/json" } }
            );
        }
    }

    return next();
});
