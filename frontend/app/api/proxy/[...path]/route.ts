/**
 * Universal backend proxy.
 *
 * Forwards all /api/proxy/* requests to the appropriate backend service,
 * injecting auth headers from the server-side session.
 *
 * Routing:
 *   /api/proxy/librarian/* → LIBRARIAN_API_URL/internal/librarian/*
 *   /api/proxy/library/*   → LIBRARIAN_API_URL/internal/library/*
 *   /api/proxy/upload      → LIBRARIAN_API_URL/internal/upload
 *   /api/proxy/secretary/* → LIBRARIAN_API_URL/internal/secretary/*
 *   /api/proxy/*           → NEXT_PUBLIC_API_URL/*
 *
 * Never exposes internal backend URLs to the browser.
 * NOTE: LIBRARIAN_API_URL is intentionally NOT prefixed with NEXT_PUBLIC_ —
 *       it is a server-side-only variable and must not be embedded in the
 *       client bundle.
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
// Server-only — no NEXT_PUBLIC_ prefix so it is never sent to the browser
const LIBRARIAN_URL = process.env.LIBRARIAN_API_URL ?? "http://localhost:8001";

/** Segments that are served by the Librarian API (including Secretary) */
const LIBRARIAN_PREFIXES = new Set(["librarian", "library", "upload", "secretary"]);

async function handler(req: NextRequest, { params }: { params: { path: string[] } }) {
  const session = await auth();

  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const pathSegments = params.path ?? [];
  const relPath = pathSegments.join("/");
  const firstSegment = pathSegments[0] ?? "";

  const isLibrarianService = LIBRARIAN_PREFIXES.has(firstSegment);
  const base = isLibrarianService ? LIBRARIAN_URL : API_URL;
  const upstreamPath = isLibrarianService ? `/internal/${relPath}` : `/${relPath}`;

  const upstreamUrl = `${base}${upstreamPath}`;

  const user = session.user as Record<string, string>;

  // Build forwarded headers
  const headers = new Headers();
  headers.set("X-User-ID", user.id ?? "");
  headers.set("X-Tenant-ID", (user as { tenantId?: string }).tenantId ?? "");

  // Forward body for mutating methods
  let body: BodyInit | undefined;
  if (["POST", "PUT", "PATCH"].includes(req.method)) {
    const contentType = req.headers.get("Content-Type") ?? "";
    if (contentType.includes("multipart/form-data")) {
      body = await req.formData();
      // Do NOT set Content-Type for multipart — fetch sets the boundary automatically
    } else {
      body = await req.text();
      headers.set("Content-Type", contentType || "application/json");
    }
  } else {
    const contentType = req.headers.get("Content-Type");
    if (contentType) headers.set("Content-Type", contentType);
  }

  try {
    const res = await fetch(upstreamUrl, {
      method: req.method,
      headers,
      body,
    });

    const responseBody = await res.arrayBuffer();
    return new NextResponse(responseBody, {
      status: res.status,
      headers: {
        "Content-Type": res.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch (err) {
    console.error("[proxy] upstream error:", err);
    return NextResponse.json({ error: "Backend unavailable" }, { status: 502 });
  }
}

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
