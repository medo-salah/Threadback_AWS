/**
 * MCP Endpoint Resolution Strategy.
 *
 * Local development:
 *   http://localhost:8000/mcp
 *
 * Production / deployed environment:
 *   /mcp (same-origin, resolving to window.location.origin + '/mcp')
 *
 * Never hardcodes any domain name or cloud provider.
 */

export function resolveMcpEndpoint(): string {
  // 1. Explicit environment variable override if provided
  if (import.meta.env.VITE_MCP_URL) {
    return import.meta.env.VITE_MCP_URL
  }

  // 2. In production (built and served from the FastAPI backend container)
  if (import.meta.env.PROD) {
    return '/mcp'
  }

  // 3. In local development (Vite dev server)
  return 'http://localhost:8000/mcp'
}
