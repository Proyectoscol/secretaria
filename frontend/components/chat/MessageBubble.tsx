"use client";
import { useState } from "react";
import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Copy, Check, FileText } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import type { Message, Citation } from "@/types/chat";

function CitationChip({ citation }: { citation: Citation }) {
  return (
    <Link
      href={`/library/${citation.documentId}`}
      className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-[11px] font-medium text-primary transition-colors cursor-pointer"
      style={{
        background: "oklch(0.62 0.22 264 / 0.1)",
        border: "1px solid oklch(0.62 0.22 264 / 0.25)",
      }}
    >
      <FileText size={11} />
      <span className="truncate max-w-[200px]">{citation.filename}</span>
      {citation.sectionTitle && (
        <span className="text-primary/70">— {citation.sectionTitle}</span>
      )}
      {citation.page && <span className="text-primary/60">p.{citation.page}</span>}
    </Link>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button
      onClick={copy}
      className="opacity-0 group-hover:opacity-100 p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-all"
    >
      {copied ? <Check size={13} className="text-green-500" /> : <Copy size={13} />}
    </button>
  );
}

interface Props {
  message: Message;
}

export function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={cn("flex gap-3 px-4 py-1 group", isUser && "justify-end")}
    >
      {!isUser && (
        <div
          className="w-7 h-7 rounded-full flex items-center justify-center shrink-0 mt-0.5"
          style={{
            background: "oklch(0.62 0.22 264 / 0.15)",
            border: "1px solid oklch(0.62 0.22 264 / 0.25)",
          }}
        >
          <span className="text-[10px] font-bold text-primary">K</span>
        </div>
      )}

      <div className={cn("max-w-[85%] md:max-w-[70%]", isUser && "items-end")}>
        {/* Attachment indicator */}
        {message.attachmentName && (
          <div
            className="flex items-center gap-1.5 mb-1.5 px-2.5 py-1.5 rounded-lg text-xs text-primary w-fit"
            style={{
              background: "oklch(0.62 0.22 264 / 0.1)",
              border: "1px solid oklch(0.62 0.22 264 / 0.2)",
            }}
          >
            <FileText size={11} />
            {message.attachmentName}
          </div>
        )}

        {/* Bubble */}
        <div
          className={cn(
            "relative rounded-2xl px-4 py-3",
            isUser
              ? "bg-primary text-primary-foreground rounded-br-sm"
              : "bg-card border border-border rounded-bl-sm"
          )}
        >
          {!isUser && (
            <div className="absolute -top-1 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
              <CopyButton text={message.content} />
            </div>
          )}

          {isUser ? (
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{message.content}</p>
          ) : (
            <>
              {message.isStreaming && !message.content ? (
                <div className="flex gap-1 py-1">
                  {[0, 1, 2].map((i) => (
                    <motion.div
                      key={i}
                      animate={{ opacity: [0.3, 1, 0.3] }}
                      transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.2 }}
                      className="w-1.5 h-1.5 rounded-full bg-muted-foreground"
                    />
                  ))}
                </div>
              ) : (
                <div className="prose-chat">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {message.content}
                  </ReactMarkdown>
                </div>
              )}
            </>
          )}
        </div>

        {/* Citations */}
        {message.citations && message.citations.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {message.citations.map((c, i) => (
              <CitationChip key={i} citation={c} />
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}
