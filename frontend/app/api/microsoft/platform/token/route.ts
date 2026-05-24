/**
 * Returns the current platform token status + decrypted access token.
 * Used by useMicrosoftPlatformToken() hook.
 */
import { NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { decryptToken, encryptToken } from "@/lib/crypto";

export async function GET() {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const user = session.user as { id: string };
  const record = await prisma.microsoftPlatformToken.findUnique({
    where: { userId: user.id },
  });

  if (!record) {
    return NextResponse.json({ connected: false });
  }

  return NextResponse.json({
    connected: true,
    accessToken: decryptToken(record.encryptedAccessToken),
    expiresAt: record.tokenExpiresAt.toISOString(),
    scopesGranted: record.scopesGranted,
  });
}
