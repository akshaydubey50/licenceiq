/** Wire contracts mirror backend/app/models/document.py. */
export enum ProcessingStatus {
  UPLOADED = "UPLOADED",
  PROCESSING = "PROCESSING",
  READY = "READY",
  READY_WITH_WARNINGS = "READY_WITH_WARNINGS",
  FAILED = "FAILED",
}

export interface Evidence {
  document_id: string;
  /** One-based page number within this document. */
  page_number: number;
  source_text: string;
  block_id: string | null;
  /** OCR providers may omit confidence and geometry when they cannot support them reliably. */
  confidence: number | null;
  bounding_box: [number, number, number, number] | null;
}

/** Page-level reading evidence; Phase 2 deliberately does not infer licence fields. */
export type ReadingBlock = Evidence;

export interface DocumentPage {
  document_id: string;
  page_number: number;
  text: string;
  method: "native_text" | "ocr";
  blocks: ReadingBlock[];
}

export interface DocumentReading {
  document_id: string;
  status: "READ" | "READ_WITH_WARNINGS";
  pages: DocumentPage[];
  warnings: string[];
  created_at: string;
}

export interface ExtractedField {
  value: string | null;
  raw_value: string | null;
  evidence: Evidence[];
  current_value: string | null;
  is_edited: boolean;
  warnings: string[];
}

export interface ExtractedLicence {
  document_id: string;
  full_name: ExtractedField;
  licence_number: ExtractedField;
  date_of_birth: ExtractedField;
  date_of_issue: ExtractedField;
  date_of_expiry: ExtractedField;
  address: ExtractedField;
  vehicle_classes: ExtractedField[];
  issuing_authority: ExtractedField;
  other_information: Record<string, ExtractedField>;
}

export interface ExtractionResult {
  document_id: string;
  status: "EXTRACTED" | "EXTRACTED_WITH_WARNINGS";
  licence: ExtractedLicence;
  warnings: string[];
  created_at: string;
}

export interface ReviewedField {
  current_value: string | null;
  is_edited: boolean;
}

export interface ReviewedVehicleClasses {
  current_value: string[];
  is_edited: boolean;
}

export interface ReviewedLicence {
  document_id: string;
  full_name: ReviewedField;
  licence_number: ReviewedField;
  date_of_birth: ReviewedField;
  date_of_issue: ReviewedField;
  date_of_expiry: ReviewedField;
  address: ReviewedField;
  vehicle_classes: ReviewedVehicleClasses;
  issuing_authority: ReviewedField;
  other_information: Record<string, ReviewedField>;
}

export interface FieldsResult {
  document_id: string;
  extraction: ExtractionResult;
  reviewed: ReviewedLicence;
  updated_at: string | null;
}

export interface ReviewUpdateFields {
  full_name: string | null;
  licence_number: string | null;
  date_of_birth: string | null;
  date_of_issue: string | null;
  date_of_expiry: string | null;
  address: string | null;
  vehicle_classes: string[];
  issuing_authority: string | null;
  other_information: Record<string, string | null>;
}

export interface ReviewUpdate {
  fields: ReviewUpdateFields;
}

export interface QuestionCitation {
  block_id: string;
  /** One-based page number within this document. */
  page_number: number;
}

export interface QuestionResult {
  document_id: string;
  question: string;
  status: "ANSWERED" | "UNAVAILABLE";
  answer: string;
  citations: QuestionCitation[];
  created_at: string;
}

export interface Document {
  document_id: string;
  filename: string;
  mime_type: "application/pdf" | "image/png" | "image/jpeg";
  size_bytes: number;
  status: ProcessingStatus;
  created_at: string;
  page_count: number | null;
  warnings: string[];
}
