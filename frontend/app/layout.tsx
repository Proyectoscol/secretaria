import type { Metadata, Viewport } from "next";
import { Sora, Plus_Jakarta_Sans } from "next/font/google";
import { SessionProvider } from "next-auth/react";
import { Toaster } from "sonner";
import "./globals.css";

const sora = Sora({
  subsets: ["latin"],
  variable: "--font-sora",
  display: "swap",
  weight: ["300", "400", "500", "600", "700", "800"],
});

const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-jakarta",
  display: "swap",
  weight: ["300", "400", "500", "600", "700", "800"],
  style: ["normal", "italic"],
});

export const metadata: Metadata = {
  title: "OpenClaw KOS",
  description: "Knowledge Operating System — gestión de conocimiento empresarial con IA",
  icons: { icon: "/favicon.ico" },
};

export const viewport: Viewport = {
  themeColor: "#0b0b0f",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className={`${sora.variable} ${jakarta.variable} dark`} suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans antialiased">
        <SessionProvider>
          {children}
          <Toaster
            theme="dark"
            position="top-right"
            toastOptions={{
              style: {
                background: "hsl(240 9% 8%)",
                border: "1px solid hsl(240 7% 16%)",
                color: "hsl(210 20% 93%)",
                fontFamily: "var(--font-jakarta)",
              },
            }}
          />
        </SessionProvider>
      </body>
    </html>
  );
}
