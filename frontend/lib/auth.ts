import NextAuth from "next-auth";
import { PrismaAdapter } from "@auth/prisma-adapter";
import Credentials from "next-auth/providers/credentials";
import bcrypt from "bcryptjs";
import { prisma } from "./prisma";
import { loginSchema, emailDomainRefinement } from "./validators";

// ── Microsoft provider as OAuth2 (not OIDC) ──────────────────────────────────
// Using the built-in MicrosoftEntraID provider with tenantId="common" triggers:
//   "response body issuer does not match expectedIssuer"
// because Microsoft's /common discovery doc returns the literal template string
// "{tenantid}" as the issuer while the ID token carries the real tenant GUID.
// Switching to type:"oauth" with explicit endpoints bypasses OIDC issuer
// validation entirely. Graph /v1.0/me is used as userinfo — its "id" field
// is the Azure Object ID (OID), equivalent to the "oid" claim in OIDC tokens.
const microsoftProvider = {
  id: "microsoft-entra-id",
  name: "Microsoft",
  type: "oauth" as const,
  clientId: process.env.MICROSOFT_AUTH_CLIENT_ID as string,
  clientSecret: process.env.MICROSOFT_AUTH_CLIENT_SECRET as string,
  authorization: {
    url: "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
    params: {
      // 'openid' scope causes Microsoft to return id_token in the token response.
      // type:"oauth" uses processAuthorizationCodeOAuth2Response() which rejects
      // id_token with "Unexpected ID Token returned". Remove 'openid' so Microsoft
      // returns only an access token. User.Read is sufficient for Graph /v1.0/me.
      scope: "User.Read",
    },
  },
  token: "https://login.microsoftonline.com/common/oauth2/v2.0/token",
  userinfo: "https://graph.microsoft.com/v1.0/me",
  profile(profile: Record<string, string | null>) {
    return {
      id: profile["id"] as string,
      name: profile["displayName"] ?? profile["userPrincipalName"] ?? "",
      // 'mail' can be null for personal MSA accounts; fall back to userPrincipalName
      email: profile["mail"] ?? profile["userPrincipalName"] ?? "",
      image: null as string | null,
    };
  },
};

export const { handlers, auth, signIn, signOut } = NextAuth({
  adapter: PrismaAdapter(prisma),
  session: { strategy: "jwt" },

  providers: [
    // ── App 1: Microsoft (authentication only) ───────────────────────────────
    microsoftProvider,

    // ── Local credentials ─────────────────────────────────────────────────────
    Credentials({
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Contraseña", type: "password" },
      },
      async authorize(credentials) {
        const parsed = loginSchema.safeParse(credentials);
        if (!parsed.success) return null;

        const { email, password } = parsed.data;

        const user = await prisma.user.findUnique({ where: { email } });
        if (!user || !user.passwordHash) return null;
        if (!user.isActive) return null;

        const valid = await bcrypt.compare(password, user.passwordHash);
        if (!valid) return null;

        await prisma.user.update({
          where: { id: user.id },
          data: { lastLoginAt: new Date() },
        });

        return {
          id: user.id,
          email: user.email,
          name: user.fullName,
          image: user.avatarUrl,
          role: user.role,
          tenantId: user.tenantId,
        };
      },
    }),
  ],

  callbacks: {
    async signIn({ user, account, profile }) {
      // ── Domain validation — all providers ──────────────────────────────────
      const email = user.email ?? "";
      if (!emailDomainRefinement(email)) {
        return "/auth/error?reason=domain";
      }

      // ── Microsoft sign-in: auto-create or link account ───────────────────
      if (account?.provider === "microsoft-entra-id") {
        // Graph /v1.0/me uses "id" as the Object ID (OID); OIDC used "oid"
        const oid = (profile as { id?: string })?.id ?? "";
        const existing = await prisma.user.findUnique({ where: { email } });

        if (existing) {
          // Link Microsoft OID to existing local account
          if (!existing.microsoftAuthOid) {
            await prisma.user.update({
              where: { id: existing.id },
              data: {
                microsoftAuthOid: oid,
                source: "microsoft",
                avatarUrl: user.image ?? existing.avatarUrl,
                lastLoginAt: new Date(),
              },
            });
          }
        } else {
          // Auto-create user
          await prisma.user.create({
            data: {
              email,
              fullName: user.name ?? email.split("@")[0],
              source: "microsoft",
              microsoftAuthOid: oid,
              avatarUrl: user.image,
              tenantId: await getOrCreateTenant(email),
              emailVerified: new Date(),
            },
          });
        }
      }

      return true;
    },

    async jwt({ token, user, account }) {
      if (user) {
        const dbUser = await prisma.user.findUnique({
          where: { email: token.email! },
          include: { _count: { select: { platformToken: true } } },
        });
        if (dbUser) {
          token.userId = dbUser.id;
          token.tenantId = dbUser.tenantId;
          token.role = dbUser.role;
          token.hasPlatformToken = dbUser._count.platformToken > 0;
        }
      }
      return token;
    },

    async session({ session, token }) {
      if (session.user && token) {
        session.user.id = token.userId as string;
        (session.user as Record<string, unknown>).tenantId = token.tenantId;
        (session.user as Record<string, unknown>).role = token.role;
        (session.user as Record<string, unknown>).hasPlatformToken = token.hasPlatformToken;
      }
      return session;
    },
  },

  pages: {
    signIn: "/auth/login",
    error: "/auth/error",
    newUser: "/chat",
  },
});

async function getOrCreateTenant(email: string): Promise<string> {
  const domain = email.split("@")[1];
  let tenant = await prisma.tenant.findFirst({ where: { domain } });
  if (!tenant) {
    tenant = await prisma.tenant.create({ data: { domain, name: domain } });
  }
  return tenant.id;
}
