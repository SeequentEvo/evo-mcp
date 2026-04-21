<!--
SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated

SPDX-License-Identifier: Apache-2.0
-->

# Authentication

The Evo MCP server supports two authentication modes depending on the deployment scenario. This document explains how each mode works, including the OAuth flows, session management, and current workarounds.

## Overview

| Mode | When to use | How it works |
|------|-------------|-------------|
| **Server-managed** | Local dev, single-user, STDIO or HTTP | The MCP server authenticates directly with Bentley IMS. All clients share one identity. |
| **Client-delegated** | Shared server, multi-user, HTTP only | Each AI client authenticates independently via OAuth. The MCP server acts as an authorization server using OIDCProxy. |

## Components

```mermaid
graph TB
    subgraph Clients["AI Clients"]
        VSCode["VS Code<br/>(Copilot)"]
        Cursor[Cursor]
        Claude["Claude Desktop"]
        ADK["Google ADK /<br/>custom agents"]
    end

    subgraph MCP["Evo MCP Server"]
        FastMCP["FastMCP Runtime"]
        Proxy["OIDCProxy<br/><i>Authorization server</i>"]
        Middleware["AuthMetadata<br/>PatchMiddleware"]
        Tools["Tool Modules"]
        MCtx["ManagedAuthContext<br/><i>single shared context</i>"]
        DCtx["DelegatedAuthContext<br/><i>per-session context</i>"]

        FastMCP --> Proxy
        FastMCP --> Middleware
        FastMCP --> Tools
        Tools --> MCtx
        Tools --> DCtx
    end

    subgraph IMS["Bentley IMS (PingFederate)"]
        AuthZ["OAuth 2.0 / OIDC<br/>Authorization Server"]
    end

    subgraph Evo["Evo Platform"]
        Discovery["Discovery API"]
        WS["Workspace API"]
        Obj["Object API"]
    end

    VSCode & Cursor & Claude & ADK -- "stdio / streamable HTTP" --> FastMCP

    Proxy -- "Authorization Code + PKCE<br/>(delegated mode)" --> AuthZ
    MCtx -. "native_app / client_credentials<br/>(managed mode)" .-> AuthZ

    MCtx & DCtx -- "Bearer token" --> Discovery & WS & Obj
```

## Server-managed authentication

Used when `CLIENT_DELEGATED_AUTH=false` (the default). The MCP server handles authentication itself — either via an interactive browser login (`AUTH_METHOD=native_app`) or a service token (`AUTH_METHOD=client_credentials`).

All connecting AI clients share a single Evo identity and session. The token is cached to disk (`.cache/`) and survives server restarts.

### Sequence: native_app (interactive)

```mermaid
sequenceDiagram
    participant Client as AI Client<br/>(VS Code / Cursor)
    participant MCP as Evo MCP Server
    participant IMS as Bentley IMS
    participant Evo as Evo APIs

    Client->>MCP: MCP request (tool call)
    activate MCP

    Note over MCP: ManagedAuthContext.initialize()

    alt Cached token valid
        MCP->>MCP: Load token from .cache/
    else No valid cached token
        MCP->>IMS: Open browser → /authorize
        IMS-->>IMS: User signs in
        IMS->>MCP: Redirect with auth code
        MCP->>IMS: Exchange code for tokens
        IMS-->>MCP: Access token
        MCP->>MCP: Save token to .cache/
    end

    MCP->>Evo: API call (Bearer token)
    Evo-->>MCP: Response
    MCP-->>Client: Tool result

    deactivate MCP
```

### Sequence: client_credentials (service)

```mermaid
sequenceDiagram
    participant Client as AI Client
    participant MCP as Evo MCP Server
    participant IMS as Bentley IMS
    participant Evo as Evo APIs

    Client->>MCP: MCP request (tool call)
    activate MCP

    Note over MCP: ManagedAuthContext.initialize()

    alt Cached token valid
        MCP->>MCP: Load token from .cache/
    else No valid cached token
        MCP->>IMS: POST /token<br/>(client_id + client_secret)
        IMS-->>MCP: Access token
        MCP->>MCP: Save token to .cache/
    end

    MCP->>Evo: API call (Bearer token)
    Evo-->>MCP: Response
    MCP-->>Client: Tool result

    deactivate MCP
```

## Client-delegated authentication

Used when `CLIENT_DELEGATED_AUTH=true` with `MCP_TRANSPORT=http`. Each AI client authenticates independently — the MCP server acts as an OAuth authorization server using FastMCP's [OIDCProxy](https://gofastmcp.com/servers/auth#oidcproxy).

OIDCProxy implements the MCP authorization specification:
- **Dynamic Client Registration (DCR)** — clients register themselves
- **Authorization Code + PKCE** — browser-based user authentication proxied to Bentley IMS
- **Token management** — OIDCProxy issues its own tokens backed by upstream IMS tokens

### Full OAuth flow

```mermaid
sequenceDiagram
    participant Client as AI Client<br/>(VS Code / Cursor)
    participant MCP as Evo MCP Server<br/>(FastMCP + OIDCProxy)
    participant IMS as Bentley IMS
    participant Evo as Evo APIs

    Note over Client,MCP: 1. Discovery
    Client->>MCP: GET /mcp (or any endpoint)
    MCP-->>Client: 401 Unauthorized<br/>WWW-Authenticate: Bearer resource_metadata="..."

    Client->>MCP: GET /.well-known/oauth-authorization-server
    Note over MCP: AuthMetadataPatchMiddleware<br/>appends "none" to<br/>token_endpoint_auth_methods_supported
    MCP-->>Client: OAuth metadata (issuer, endpoints, ...)

    Note over Client,MCP: 2. Dynamic Client Registration
    Client->>MCP: POST /auth/register<br/>{redirect_uris, token_endpoint_auth_method: "none", ...}
    MCP-->>Client: {client_id, ...}

    Note over Client,IMS: 3. Authorization Code + PKCE
    Client->>MCP: GET /auth/authorize<br/>?client_id=...&code_challenge=...&scope=...
    Note over MCP: OIDCProxy strips RFC 8707<br/>"resource" parameter<br/>(forward_resource=False)
    MCP->>IMS: GET /authorize<br/>?client_id=EVO_CLIENT_ID&code_challenge=...
    IMS-->>IMS: User signs in via browser
    IMS->>MCP: GET /auth/callback?code=AUTH_CODE
    MCP->>IMS: POST /token (exchange auth code + PKCE verifier)
    IMS-->>MCP: IMS access token (upstream)

    Note over MCP: OIDCProxy stores upstream token,<br/>issues its own proxy token
    MCP-->>Client: Redirect with authorization code
    Client->>MCP: POST /auth/token (exchange code for proxy token)
    MCP-->>Client: Proxy access token

    Note over Client,Evo: 4. Authenticated MCP requests
    Client->>MCP: POST /mcp (tool call)<br/>Authorization: Bearer <proxy_token><br/>mcp-session-id: <session_id>
    activate MCP

    Note over MCP: Extract upstream IMS token<br/>from proxy token.<br/>Derive session key:<br/>sha256(user_sub + session_id)

    alt Existing session
        MCP->>MCP: Reuse DelegatedAuthContext
    else New session
        MCP->>MCP: Create DelegatedAuthContext
    end

    alt Token changed since last request
        Note over MCP: Rebuild API clients,<br/>preserve org/hub selection
    end

    MCP->>Evo: API call (IMS Bearer token)
    Evo-->>MCP: Response
    MCP-->>Client: Tool result

    deactivate MCP
```

### Key design decisions

| Decision | Rationale |
|----------|-----------|
| `forward_resource=False` | MCP clients send RFC 8707 `resource` parameter. Bentley IMS rejects unknown resource URLs with `invalid_target`. OIDCProxy strips it before forwarding to IMS. |
| `token_endpoint_auth_method: "none"` | AI clients are public OAuth clients (no client secret). IMS native/SPA apps use PKCE only. |
| Fixed `/auth/callback` path | In HTTP mode, the MCP server itself receives the IMS OAuth callback (not the evo SDK's local server). The redirect URI is `{MCP_PUBLIC_BASE_URL}/auth/callback`. |
| Composite session key | `sha256(user_sub + mcp-session-id)` prevents session-ID spoofing — even with a forged header, the `sub` claim from the JWT differs per user. |

## Session lifecycle (delegated mode)

Each authenticated client gets its own `DelegatedAuthContext` managed by a `_CleanupTTLCache`.

```mermaid
stateDiagram-v2
    [*] --> Created: First request with<br/>new session key
    Created --> Active: initialize()<br/>discovers org & hub,<br/>builds API clients

    Active --> Active: Same token →<br/>skip rebuild
    Active --> Rebuilding: Token refreshed<br/>(new upstream token)
    Rebuilding --> Active: Rebuild API clients,<br/>preserve org/hub<br/>via seed values

    Active --> Evicted: TTL expired (1h)<br/>or max sessions (1000)
    Evicted --> [*]: cleanup()<br/>remove temp dir + lock

    note right of Active
        Session key = sha256(user_sub + mcp-session-id)
        Stored in _CleanupTTLCache
        TTL resets on each request
    end note
```

### Session identity

The session key is derived from two values:

1. **`sub` claim** from the IMS JWT — identifies the user
2. **`mcp-session-id` header** — identifies the client session (set by MCP protocol)

```
session_key = sha256(user_sub + ":" + mcp_session_id)[:32]
```

If the `mcp-session-id` header is absent (fallback), the raw token is used instead — but this means a token refresh creates a new session (the old one is evicted by TTL).

### Eviction and cleanup

`_CleanupTTLCache` (subclass of `cachetools.TTLCache`) ensures prompt cleanup:

| Trigger | What happens |
|---------|-------------|
| **TTL expiry** (default: 1 hour since last access) | Context evicted on next cache operation |
| **Max size exceeded** (default: 1000 sessions) | Least-recently-used context evicted |
| **Eviction hook** | `cleanup()` called → removes temp directory; matching `session_locks` entry removed |

## Current workarounds

These patches work around upstream issues and should be removed when fixes are released.

### 1. AuthMetadataPatchMiddleware

**Problem:** The MCP Python SDK's `build_metadata()` hardcodes `token_endpoint_auth_methods_supported` to `["client_secret_post", "client_secret_basic"]`. Public clients need `"none"`.

**Workaround:** ASGI middleware intercepts `GET /.well-known/oauth-authorization-server` and appends `"none"` to the list.

**Remove when:** `mcp` SDK includes `"none"` natively in `build_metadata()`.
**Tracking:** [python-sdk#2260](https://github.com/modelcontextprotocol/python-sdk/issues/2260)

### 2. forward_resource=False

**Problem:** MCP clients send an RFC 8707 `resource` parameter (the MCP server URL). Bentley IMS has its own resource model and rejects unknown resource URLs with `invalid_target`.

**Workaround:** `OIDCProxy(forward_resource=False)` strips the parameter before forwarding to IMS.

**Remove when:** This is likely permanent for Bentley IMS deployments, since IMS does not support arbitrary RFC 8707 resource indicators. However, the `forward_resource` parameter was added upstream specifically for this use case.
**Tracking:** [fastmcp#3939](https://github.com/PrefectHQ/fastmcp/issues/3939)
