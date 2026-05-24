"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { v4 as uuid } from "uuid";

// Redirect to a new chat session immediately
export default function ChatPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace(`/chat/${uuid()}`);
  }, [router]);
  return null;
}
