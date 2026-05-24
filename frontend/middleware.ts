import { auth } from "@/lib/auth";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const ALLOWED_DOMAINS = (process.env.ALLOWED_EMAIL_DOMAIN ?? "@proyectoscall.com")
  .split(",")
  .map((d) => d.trim().toLowerCase());

export default auth(function middleware(req: NextRequest & { auth: unknown }) {
  const session = (req as { auth?: { user?: { email?: string } } }).auth;

  // Not authenticated → redirect to login
  if (!session?.user) {
    return NextResponse.redirect(new URL("/auth/login", req.url));
  }

  // Domain validation — belt-and-suspenders check on every request
  const email = session.user.email ?? "";
  const domainOk = ALLOWED_DOMAINS.some((d) => email.toLowerCase().endsWith(d));

  if (!domainOk) {
    return NextResponse.redirect(
      new URL(`/auth/error?reason=domain&email=${encodeURIComponent(email)}`, req.url)
    );
  }

  return NextResponse.next();
});

export const config = {
  matcher: [
    // Protect all app routes
    "/((?!auth|api/auth|_next/static|_next/image|favicon.ico|robots.txt).*)",
  ],
};
