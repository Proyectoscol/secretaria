import type { DocumentChunk } from "./document";

export type MessageRole = "user" | "assistant" | "system";
export type LibrarianStatus = "idle" | "searching_local" | "searching_onedrive" | "querying_db";

export interface Citation {
  filename: string;
  sectionTitle: string;
  page?: number;
  documentId: string;
  score: number;
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  citations?: Citation[];
  attachmentName?: string;
  attachmentJobId?: string;
  isStreaming?: boolean;
  createdAt: string;
}

export interface ChatSession {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  lastMessage?: string;
  messageCount: number;
}

export interface AttachedFile {
  file: File;
  name: string;
  size: number;
  type: string;
  preview?: string;
}
