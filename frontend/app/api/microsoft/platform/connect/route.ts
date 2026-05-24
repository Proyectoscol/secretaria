/**
 * Initiates the OAuth2 flow for Microsoft App 2 (platform permissions).
 * Returns a redirect URL to Microsoft's consent screen.
 */
import { NextResponse } from "next/server";
import { auth } from "@/lib/auth";

export async function POST() {
  const session = await auth();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const tenantId = process.env.MICROSOFT_PLATFORM_TENANT_ID ?? "common";
  const clientId = process.env.MICROSOFT_PLATFORM_CLIENT_ID ?? "";
  const scopes = process.env.MICROSOFT_PLATFORM_SCOPES ?? "offline_access Files.Read.All";
  const callbackUrl = `${process.env.NEXTAUTH_URL}/api/microsoft/platform/callback`;

  const params = new URLSearchParams({
    client_id: clientId,
    response_type: "code",
    redirect_uri: callbackUrl,
    scope: scopes,
    response_mode: "query",
    prompt: "consent",
  });

  const authUrl = `https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/authorize?${params}`;
  return NextResponse.json({ authUrl });
}
