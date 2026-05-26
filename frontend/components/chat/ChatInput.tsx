"use client";
import { useRef, useState, KeyboardEvent } from "react";
import { Paperclip, SendHorizonal, X, Loader2 } from "lucide-react";
import { cn, formatBytes } from "@/lib/utils";
import { useChatStore } from "@/stores/chat";
import { useDocumentUpload } from "@/hooks/useDocumentUpload";
import type { AttachedFile } from "@/types/chat";

interface Props {
  onSend: (text: string, attachment: AttachedFile | null) => Promise<void>;
  disabled?: boolean;
}

export function ChatInput({ onSend, disabled }: Props) {
  const [text, setText] = useState("");
  const { attachedFile, setAttachedFile } = useChatStore();
  const { uploading } = useDocumentUpload();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setAttachedFile({ file, name: file.name, size: file.size, type: file.type });
    e.target.value = "";
  };

  const handleSend = async () => {
    const trimmed = text.trim();
    if (!trimmed && !attachedFile) return;
    setText("");
    // Auto-resize back
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
    await onSend(trimmed, attachedFile);
    setAttachedFile(null);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value);
    // Auto-resize
    e.target.style.height = "auto";
    e.target.style.height = Math.min(e.target.scrollHeight, 180) + "px";
  };

  return (
    <div className="px-3 pb-3 pt-2 safe-bottom">
      {/* Attachment preview */}
      {attachedFile && (
        <div className="mb-2 flex items-center gap-2 px-3 py-2 rounded-lg border border-border"
             style={{ background: "oklch(0.269 0 0)" }}>
          <Paperclip size={14} className="text-primary shrink-0" />
          <span className="text-xs text-foreground flex-1 truncate">{attachedFile.name}</span>
          <span className="text-xs text-muted-foreground shrink-0">
            {formatBytes(attachedFile.size)}
          </span>
          <button
            onClick={() => setAttachedFile(null)}
            className="p-0.5 rounded text-muted-foreground hover:text-foreground min-h-[24px] min-w-[24px] flex items-center justify-center"
          >
            <X size={13} />
          </button>
        </div>
      )}

      <div className="flex items-end gap-2 rounded-xl border border-border px-3 py-2"
           style={{ background: "oklch(0.269 0 0)" }}>
        {/* Attach button */}
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || uploading}
          className={cn(
            "p-2 rounded-lg text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors",
            "min-h-[44px] min-w-[44px] flex items-center justify-center shrink-0",
            (disabled || uploading) && "opacity-50 cursor-not-allowed"
          )}
        >
          {uploading ? <Loader2 size={18} className="animate-spin" /> : <Paperclip size={18} />}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.xlsx,.pptx,.jpg,.jpeg,.png"
          capture="environment"
          className="hidden"
          onChange={handleFile}
        />

        {/* Textarea — font-size 16px prevents iOS Safari auto-zoom on focus */}
        <textarea
          ref={textareaRef}
          value={text}
          onChange={handleTextChange}
          onKeyDown={handleKeyDown}
          placeholder="Escribe tu mensaje…"
          disabled={disabled}
          rows={1}
          style={{ fontSize: "16px" }}
          className={cn(
            "flex-1 bg-transparent text-foreground placeholder:text-muted-foreground",
            "resize-none outline-none py-2 leading-relaxed",
            "max-h-[180px] overflow-y-auto scrollbar-thin"
          )}
        />

        {/* Send */}
        <button
          type="button"
          onClick={handleSend}
          disabled={disabled || (!text.trim() && !attachedFile)}
          className={cn(
            "p-2 rounded-lg transition-colors",
            "min-h-[44px] min-w-[44px] flex items-center justify-center shrink-0",
            text.trim() || attachedFile
              ? "bg-primary text-primary-foreground hover:bg-primary/90"
              : "text-muted-foreground",
            disabled && "opacity-50 cursor-not-allowed"
          )}
        >
          <SendHorizonal size={18} />
        </button>
      </div>
    </div>
  );
}
