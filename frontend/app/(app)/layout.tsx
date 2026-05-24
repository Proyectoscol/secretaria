import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { AppSidebar } from "@/components/AppSidebar";
import { WebSocketProvider } from "@/components/WebSocketProvider";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();
  if (!session) redirect("/auth/login");

  return (
    <WebSocketProvider>
      <div className="flex h-screen w-screen overflow-hidden bg-background">
        <AppSidebar />
        <main className="flex-1 flex flex-col overflow-hidden min-w-0">
          {children}
        </main>
      </div>
    </WebSocketProvider>
  );
}
