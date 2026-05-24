export type DocumentStatus = "pending" | "processing" | "done" | "failed" | "quarantined";
export type FileType = "pdf" | "docx" | "xlsx" | "pptx" | "image";

export interface KosDocument {
  id: string;
  tenantId: string;
  filenameOriginal: string;
  fileType: FileType;
  title?: string;
  authors?: string[];
  pageCount?: number;
  languageDetected?: string;
  processingStatus: DocumentStatus;
  processedAt?: string;
  createdAt: string;
  chunkCount?: number;
  canonicalPath?: string;
}

export interface DocumentChunk {
  chunkId: string;
  documentId: string;
  filename: string;
  sectionTitle: string;
  contentText: string;
  contentType: "text" | "table" | "figure_caption" | "header" | "list";
  pageNumber?: number;
  score: number;
  searchMethod: "semantic" | "fulltext" | "onedrive_index" | "onedrive_graph";
}

export interface DocumentFigure {
  id: string;
  figureIndex: number;
  caption: string;
  imagePath: string;
  pageNumber?: number;
}

export interface DocumentDetail extends KosDocument {
  sections: Array<{ title: string; level: number; content: string; page?: number }>;
  figures: DocumentFigure[];
  keywords?: string[];
  organization?: string;
  subject?: string;
}

export interface UploadJob {
  jobId: string;
  status: "queued" | "processing" | "done" | "failed";
  filename: string;
  documentId?: string;
  error?: string;
  progress?: number;
}
