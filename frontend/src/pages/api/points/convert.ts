/**
 * API Proxy: Convert Points to Money
 * 
 * Proxies conversion requests to the backend API with proper authentication.
 */

import type { APIRoute } from 'astro';

export const POST: APIRoute = async ({ request, cookies }) => {
    const token = cookies.get('access_token')?.value;
    
    if (!token) {
        return new Response(
            JSON.stringify({ success: false, error: 'Not authenticated' }),
            { status: 401, headers: { 'Content-Type': 'application/json' } }
        );
    }
    
    try {
        const body = await request.json();
        const apiUrl = import.meta.env.PUBLIC_API_URL || 'http://localhost:8002';
        
        const response = await fetch(`${apiUrl}/api/points-conversion/convert`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`,
            },
            body: JSON.stringify(body),
        });
        
        const data = await response.json();
        
        return new Response(
            JSON.stringify(data),
            {
                status: response.status,
                headers: { 'Content-Type': 'application/json' },
            }
        );
    } catch (error) {
        console.error('Points conversion proxy error:', error);
        return new Response(
            JSON.stringify({
                success: false,
                error: 'Failed to connect to backend API',
                detail: error instanceof Error ? error.message : 'Unknown error',
            }),
            { status: 500, headers: { 'Content-Type': 'application/json' } }
        );
    }
};
