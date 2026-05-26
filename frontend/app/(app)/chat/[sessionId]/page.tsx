"use client";
import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { v4 as uuid } from "uuid";
import { useChatStore } from "@/stores/chat";
import { MessageBubble } from "@/components/chat/MessageBubble";
import { ChatInput } from "@/components/chat/ChatInput";
import { LibrarianStatusBar } from "@/components/chat/LibrarianStatusBar";
import api from "@/lib/api";
import { useDocumentUpload } from "@/hooks/useDocumentUpload";
import type { Message, AttachedFile } from "@/types/chat";

export default function ChatSessionPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { data: session } = useSession();
  const { messages, addMessage, updateMessage, isStreaming, setStreaming } = useChatStore();
  const bottomRef = useRef<HTMLDivElement>(null);
  const { upload } = useDocumentUpload();
  const sessionMessages = messages[sessionId] ?? [];
  const user = session?.user as Record<string, string> | undefined;

  // Auto-scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [sessionMessages.length, isStreaming]);

  const handleSend = async (text: string, attachment: AttachedFile | null) => {
    if (!user) return;

    // Add user message
    const userMsg: Message = {
      id: uuid(),
      role: "user",
      content: text,
      attachmentName: attachment?.name,
      createdAt: new Date().toISOString(),
    };
    addMessage(sessionId, userMsg);

    // Placeholder assistant message
    const assistantId = uuid();
    const placeholder: Message = {
      id: assistantId,
      role: "assistant",
      content: "",
      isStreaming: true,
      createdAt: new Date().toISOString(),
    };
    addMessage(sessionId, placeholder);
    setStreaming(true);

    try {
      // If attachment, upload first
      let attachmentContext = {};
      if (attachment) {
        const job = await upload(attachment.file);
        if (job) {
          attachmentContext = {
            context_hints: {
              attached_file: {
                path: `/tmp/${job.jobId}/${attachment.name}`,
                type: attachment.type.split("/")[1] ?? "pdf",
                name: attachment.name,
              },
            },
          };
        }
      }

      const res = await api.post("/librarian/query", {
        query: text,
        tenant_id: user.tenantId,
        user_id: user.id,
        session_id: sessionId,
        ...attachmentContext,
      });

      const data = res.data as {
        answer_text: string;
        citations: Array<{
          filename: string;
          section_title: string;
          page?: number;
          document_id?: string;
          score: number;
        }>;
      };

      updateMessage(sessionId, assistantId, {
        content: data.answer_text,
        isStreaming: false,
        citations: (data.citations ?? []).map((c) => ({
          filename: c.filename,
          sectionTitle: c.section_title,
          page: c.page,
          documentId: c.document_id ?? "",
          score: c.score,
        })),
      });
    } catch (err) {
      updateMessage(sessionId, assistantId, {
        content: "Lo siento, ocurrió un error al procesar tu consulta. Intenta nuevamente.",
        isStreaming: false,
      });
    } finally {
      setStreaming(false);
    }
  };

  return (
    <div className="flex flex-col h-full pt-14 md:pt-0">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto py-4 scrollbar-thin">
        {sessionMessages.length === 0 && (
          <div className="h-full flex items-center justify-center px-4">
            <div className="text-center max-w-xs">
              <div
                className="w-16 h-16 rounded-2xl bg-primary flex items-center justify-center mx-auto mb-5 shadow-lg"
                style={{ boxShadow: "0 8px 32px oklch(0.62 0.22 264 / 0.3)" }}
              >
                <span className="text-2xl font-black text-primary-foreground font-display select-none">K</span>
              </div>
              <p className="font-display text-lg font-semibold text-foreground mb-2">
                Bibliotecario KOS
              </p>
              <p className="text-sm text-muted-foreground leading-relaxed">
                Pregunta sobre tus documentos, adjunta archivos o busca en tu base de conocimiento.
              </p>
            </div>
          </div>
        )}
        {sessionMessages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Librarian status */}
      <LibrarianStatusBar />

      {/* Input */}
      <ChatInput onSend={handleSend} disabled={isStreaming} />
    </div>
  );
}
