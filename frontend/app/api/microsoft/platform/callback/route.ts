/**
 * OAuth2 callback for Microsoft App 2.
 * Exchanges the code for tokens, encrypts them, and stores them in the DB.
 */
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { encryptToken } from "@/lib/crypto";

export async function GET(req: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.redirect(new URL("/auth/login", req.url));
  }

  const code = req.nextUrl.searchParams.get("code");
  const error = req.nextUrl.searchParams.get("error");

  if (error || !code) {
    return NextResponse.redirect(
      new URL(`/settings/microsoft?error=${error ?? "missing_code"}`, req.url)
    );
  }

  const clientId = process.env.MICROSOFT_PLATFORM_CLIENT_ID!;
  const clientSecret = process.env.MICROSOFT_PLATFORM_CLIENT_SECRET!;
  const tenantId = process.env.MICROSOFT_PLATFORM_TENANT_ID ?? "common";
  const callbackUrl = `${process.env.NEXTAUTH_URL}/api/microsoft/platform/callback`;

  try {
    const tokenRes = await fetch(
      `https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/token`,
      {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          client_id: clientId,
          client_secret: clientSecret,
          code,
          redirect_uri: callbackUrl,
          grant_type: "authorization_code",
        }),
      }
    );

    const tokens = await tokenRes.json();
    if (!tokens.access_token) throw new Error("No access token");

    const scopes: string[] = (tokens.scope ?? "").split(" ");
    const expiresAt = new Date(Date.now() + tokens.expires_in * 1000);

    // Fetch MS user ID
    let microsoftUserId: string | undefined;
    try {
      const meRes = await fetch("https://graph.microsoft.com/v1.0/me?$select=id", {
        headers: { Authorization: `Bearer ${tokens.access_token}` },
      });
      const me = await meRes.json();
      microsoftUserId = me.id;
    } catch {}

    const user = session.user as { id: string };

    await prisma.microsoftPlatformToken.upsert({
      where: { userId: user.id },
      create: {
        userId: user.id,
        encryptedAccessToken: encryptToken(tokens.access_token),
        encryptedRefreshToken: encryptToken(tokens.refresh_token ?? ""),
        tokenExpiresAt: expiresAt,
        scopesGranted: scopes,
        microsoftUserId,
      },
      update: {
        encryptedAccessToken: encryptToken(tokens.access_token),
        encryptedRefreshToken: encryptToken(tokens.refresh_token ?? ""),
        tokenExpiresAt: expiresAt,
        scopesGranted: scopes,
        microsoftUserId,
        lastRefreshedAt: new Date(),
      },
    });

    return NextResponse.redirect(new URL("/settings/microsoft?connected=1", req.url));
  } catch (err) {
    console.error("[microsoft/platform/callback]", err);
    return NextResponse.redirect(new URL("/settings/microsoft?error=token_exchange", req.url));
  }
}
