import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { prisma } from "@/lib/prisma";
import { registerSchema, emailDomainRefinement } from "@/lib/validators";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const parsed = registerSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.errors[0].message },
      { status: 400 }
    );
  }

  const { fullName, email, password } = parsed.data;

  // Validate domain (layer 1)
  if (!emailDomainRefinement(email)) {
    return NextResponse.json(
      { error: "Dominio de correo no autorizado" },
      { status: 403 }
    );
  }

  // Check existing user
  const existing = await prisma.user.findUnique({ where: { email } });
  if (existing) {
    return NextResponse.json(
      { error: "Ya existe una cuenta con este correo" },
      { status: 409 }
    );
  }

  const passwordHash = await bcrypt.hash(password, 12);

  // Get or create tenant based on email domain
  const domain = email.split("@")[1];
  let tenant = await prisma.tenant.findFirst({ where: { domain } });
  if (!tenant) {
    tenant = await prisma.tenant.create({ data: { domain, name: domain } });
  }

  await prisma.user.create({
    data: {
      email,
      fullName,
      passwordHash,
      tenantId: tenant.id,
      source: "local",
      emailVerified: new Date(),
    },
  });

  return NextResponse.json({ success: true }, { status: 201 });
}
