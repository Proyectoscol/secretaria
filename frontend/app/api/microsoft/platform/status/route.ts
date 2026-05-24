import { NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function GET() {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const user = session.user as { id: string };
  const record = await prisma.microsoftPlatformToken.findUnique({
    where: { userId: user.id },
    select: { scopesGranted: true, connectedAt: true, microsoftUserId: true, tokenExpiresAt: true },
  });
  if (!record) return NextResponse.json({ connected: false, scopesGranted: [] });
  return NextResponse.json({
    connected: true,
    scopesGranted: record.scopesGranted,
    connectedAt: record.connectedAt?.toISOString(),
    microsoftUserId: record.microsoftUserId,
    expiresAt: record.tokenExpiresAt?.toISOString(),
  });
}
