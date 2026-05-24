import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { AppSidebar } from "@/components/AppSidebar";
import { WebSocketProvider } from "@/components/WebSocketProvider";
import TokenExpiryBanner from "@/components/TokenExpiryBanner";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();
  if (!session) redirect("/auth/login");

  return (
    <WebSocketProvider>
      <div className="flex flex-col h-screen w-screen overflow-hidden bg-background">
        {/* Token expiry banner — client component, polls every 60 s */}
        <TokenExpiryBanner />
        <div className="flex flex-1 overflow-hidden min-h-0">
          <AppSidebar />
          <main className="flex-1 flex flex-col overflow-hidden min-w-0">
            {children}
          </main>
        </div>
      </div>
    </WebSocketProvider>
  );
}
