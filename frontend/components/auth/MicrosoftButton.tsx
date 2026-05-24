"use client";
import { signIn } from "next-auth/react";
import { useState } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  className?: string;
}

export function MicrosoftButton({ className }: Props) {
  const [loading, setLoading] = useState(false);

  const handleClick = async () => {
    setLoading(true);
    await signIn("microsoft-entra-id", { callbackUrl: "/chat" });
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={loading}
      className={cn(
        "flex items-center justify-center gap-3 h-11 px-4 rounded-lg",
        "border border-border bg-secondary hover:bg-secondary/70",
        "text-sm font-medium text-foreground transition-colors",
        "disabled:opacity-60 disabled:cursor-not-allowed",
        "min-h-[44px]",
        className
      )}
    >
      {loading ? (
        <Loader2 size={16} className="animate-spin" />
      ) : (
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <rect width="8.5" height="8.5" fill="#F25022" />
          <rect x="9.5" width="8.5" height="8.5" fill="#7FBA00" />
          <rect y="9.5" width="8.5" height="8.5" fill="#00A4EF" />
          <rect x="9.5" y="9.5" width="8.5" height="8.5" fill="#FFB900" />
        </svg>
      )}
      {loading ? "Redirigiendo…" : "Continuar con Microsoft"}
    </button>
  );
}
