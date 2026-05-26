"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut, useSession } from "next-auth/react";
import { motion, AnimatePresence } from "framer-motion";
import { useState } from "react";
import {
  MessageSquare,
  BookOpen,
  Settings,
  LogOut,
  Menu,
  X,
  ChevronRight,
  Mail,
} from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/chat",             label: "Chat",       icon: MessageSquare },
  { href: "/mail",             label: "Correo",     icon: Mail },
  { href: "/library",          label: "Biblioteca", icon: BookOpen },
  { href: "/settings/profile", label: "Ajustes",   icon: Settings },
];

function NavItem({
  href,
  label,
  Icon,
  active,
  collapsed,
}: {
  href: string;
  label: string;
  Icon: React.ElementType;
  active: boolean;
  collapsed: boolean;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-150",
        "text-sm font-medium min-h-[44px]",
        active
          ? "bg-primary/10 text-primary amber-glow"
          : "text-muted-foreground hover:text-foreground hover:bg-secondary/60"
      )}
    >
      <Icon size={18} className="shrink-0" />
      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.span
            initial={{ opacity: 0, width: 0 }}
            animate={{ opacity: 1, width: "auto" }}
            exit={{ opacity: 0, width: 0 }}
            className="overflow-hidden whitespace-nowrap"
          >
            {label}
          </motion.span>
        )}
      </AnimatePresence>
    </Link>
  );
}

export function AppSidebar() {
  const pathname = usePathname();
  const { data: session } = useSession();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const user = session?.user as Record<string, string> | undefined;

  const initials = user?.name
    ?.split(" ")
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase() ?? "??";

  const sidebar = (
    <motion.aside
      animate={{ width: collapsed ? 64 : 220 }}
      transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
      className={cn(
        "hidden md:flex flex-col h-screen border-r border-border bg-card/50",
        "shrink-0 overflow-hidden select-none"
      )}
    >
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 py-4 h-14 border-b border-border shrink-0">
        <AnimatePresence initial={false}>
          {!collapsed && (
            <motion.span
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="font-display font-bold text-base text-foreground truncate"
            >
              KOS
            </motion.span>
          )}
        </AnimatePresence>
        <button
          onClick={() => setCollapsed((v) => !v)}
          className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
        >
          {collapsed ? <ChevronRight size={16} /> : <Menu size={16} />}
        </button>
      </div>

      {/* ── Nav ────────────────────────────────────────────────────────────── */}
      <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto scrollbar-thin">
        {NAV.map(({ href, label, icon: Icon }) => (
          <NavItem
            key={href}
            href={href}
            label={label}
            Icon={Icon}
            active={pathname.startsWith(href)}
            collapsed={collapsed}
          />
        ))}
      </nav>

      {/* ── User footer ────────────────────────────────────────────────────── */}
      <div className="px-2 pb-4 border-t border-border pt-3">
        <div
          className={cn(
            "flex items-center gap-2.5 px-2 py-2 rounded-lg",
            collapsed && "justify-center"
          )}
        >
          <Avatar className="h-7 w-7 shrink-0">
            <AvatarImage src={user?.image ?? ""} />
            <AvatarFallback className="text-xs bg-primary/20 text-primary font-semibold">
              {initials}
            </AvatarFallback>
          </Avatar>
          <AnimatePresence initial={false}>
            {!collapsed && (
              <motion.div
                initial={{ opacity: 0, width: 0 }}
                animate={{ opacity: 1, width: "auto" }}
                exit={{ opacity: 0, width: 0 }}
                className="flex-1 overflow-hidden"
              >
                <p className="text-xs font-semibold truncate text-foreground leading-tight">
                  {user?.name}
                </p>
                <p className="text-[10px] text-muted-foreground truncate">{user?.email}</p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        <button
          onClick={() => signOut({ callbackUrl: "/auth/login" })}
          className={cn(
            "flex items-center gap-2.5 px-3 py-2 rounded-lg w-full",
            "text-xs text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors",
            "mt-1 min-h-[36px]",
            collapsed && "justify-center"
          )}
        >
          <LogOut size={14} />
          {!collapsed && "Cerrar sesión"}
        </button>
      </div>
    </motion.aside>
  );

  // ── Mobile drawer ──────────────────────────────────────────────────────────
  const mobileSidebar = (
    <AnimatePresence>
      {mobileOpen && (
        <motion.div
          initial={{ x: "-100%" }}
          animate={{ x: 0 }}
          exit={{ x: "-100%" }}
          transition={{ type: "spring", stiffness: 400, damping: 40 }}
          className="fixed inset-0 z-50 flex md:hidden"
        >
          <div className="w-64 h-full bg-card border-r border-border flex flex-col safe-top">
            <div className="flex items-center justify-between px-4 py-4 border-b border-border">
              <span className="font-display font-bold text-lg text-foreground">KOS</span>
              <button onClick={() => setMobileOpen(false)} className="p-2">
                <X size={18} className="text-muted-foreground" />
              </button>
            </div>
            <nav className="flex-1 px-3 py-4 space-y-1">
              {NAV.map(({ href, label, icon: Icon }) => (
                <Link
                  key={href}
                  href={href}
                  onClick={() => setMobileOpen(false)}
                  className={cn(
                    "flex items-center gap-3 px-3 py-3 rounded-lg text-sm font-medium min-h-[48px]",
                    pathname.startsWith(href)
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:text-foreground hover:bg-secondary"
                  )}
                >
                  <Icon size={18} />
                  {label}
                </Link>
              ))}
            </nav>
          </div>
          <div
            className="flex-1 bg-background/60 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
          />
        </motion.div>
      )}
    </AnimatePresence>
  );

  return (
    <>
      {sidebar}
      {mobileSidebar}
      {/* Mobile top bar */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-40 h-14 bg-card/80 backdrop-blur-md border-b border-border flex items-center px-4 gap-3 safe-top">
        <button
          onClick={() => setMobileOpen(true)}
          className="p-2 -ml-2 min-h-[44px] min-w-[44px] flex items-center justify-center"
        >
          <Menu size={20} className="text-foreground" />
        </button>
        <span className="font-display font-bold text-base text-foreground flex-1">KOS</span>
        <Avatar className="h-7 w-7">
          <AvatarImage src={user?.image ?? ""} />
          <AvatarFallback className="text-xs bg-primary/20 text-primary font-semibold">
            {initials}
          </AvatarFallback>
        </Avatar>
      </div>
    </>
  );
}
