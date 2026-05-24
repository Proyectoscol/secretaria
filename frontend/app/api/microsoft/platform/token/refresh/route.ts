import { NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { decryptToken, encryptToken } from "@/lib/crypto";

export async function POST() {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const user = session.user as { id: string };
  const record = await prisma.microsoftPlatformToken.findUnique({
    where: { userId: user.id },
  });

  if (!record) return NextResponse.json({ error: "No token" }, { status: 404 });

  const refreshToken = decryptToken(record.encryptedRefreshToken);
  const clientId = process.env.MICROSOFT_PLATFORM_CLIENT_ID!;
  const clientSecret = process.env.MICROSOFT_PLATFORM_CLIENT_SECRET!;
  const tenantId = process.env.MICROSOFT_PLATFORM_TENANT_ID ?? "common";

  try {
    const res = await fetch(
      `https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/token`,
      {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          client_id: clientId,
          client_secret: clientSecret,
          refresh_token: refreshToken,
          grant_type: "refresh_token",
        }),
      }
    );
    const tokens = await res.json();
    if (!tokens.access_token) throw new Error("Refresh failed");

    const expiresAt = new Date(Date.now() + tokens.expires_in * 1000);
    await prisma.microsoftPlatformToken.update({
      where: { userId: user.id },
      data: {
        encryptedAccessToken: encryptToken(tokens.access_token),
        ...(tokens.refresh_token && {
          encryptedRefreshToken: encryptToken(tokens.refresh_token),
        }),
        tokenExpiresAt: expiresAt,
        lastRefreshedAt: new Date(),
      },
    });

    return NextResponse.json({
      accessToken: tokens.access_token,
      expiresAt: expiresAt.toISOString(),
    });
  } catch {
    return NextResponse.json({ error: "Refresh failed" }, { status: 401 });
  }
}
