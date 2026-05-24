/**
 * GET /api/proxy/notifications/unread
 *
 * Dedicated route for unread notifications.  Kept separate from the universal
 * catch-all proxy so callers have a stable, self-documenting contract and the
 * polling logic in TokenExpiryBanner is easy to reason about.
 *
 * Calls: LIBRARIAN_URL/internal/secretary/notifications/unread
 *   – injects X-User-ID and X-Tenant-ID from the server-side session
 *   – a user can ONLY receive their own notifications (enforced in the backend)
 *   – returns 401 when the session has expired (banner stops showing)
 */
import { NextResponse } from "next/server";
import { auth } from "@/lib/auth";

// Server-only — no NEXT_PUBLIC_ so it never reaches the browser bundle
const LIBRARIAN_URL =
  process.env.LIBRARIAN_API_URL ?? "http://localhost:8001";

export async function GET() {
  const session = await auth();

  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const user = session.user as Record<string, string>;
  const userId   = user.id       ?? "";
  const tenantId = (user as { tenantId?: string }).tenantId ?? "";

  try {
    const res = await fetch(
      `${LIBRARIAN_URL}/internal/secretary/notifications/unread`,
      {
        method: "GET",
        headers: {
          "X-User-ID":   userId,
          "X-Tenant-ID": tenantId,
          "Content-Type": "application/json",
        },
        // Next.js fetch cache: revalidate every 30 s so repeated polls don't
        // hammer the backend — the browser still fires every 60 s via SWR.
        next: { revalidate: 30 },
      },
    );

    const body = await res.json();

    return NextResponse.json(body, { status: res.status });
  } catch (err) {
    console.error("[notifications/unread] upstream error:", err);
    return NextResponse.json({ error: "Backend unavailable" }, { status: 502 });
  }
}
