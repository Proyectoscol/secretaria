import { NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function DELETE() {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const user = session.user as { id: string };
  await prisma.microsoftPlatformToken.deleteMany({ where: { userId: user.id } });
  return NextResponse.json({ disconnected: true });
}
