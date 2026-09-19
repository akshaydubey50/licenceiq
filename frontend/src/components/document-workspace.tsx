"use client";

import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from "react";
import { ApiError, request } from "@/lib/api-client";
import { Icon } from "@/components/icon";
import { publicEnv } from "@/lib/env";
import type { WorkspaceAccessMode } from "@/types/auth";
import type {
  Document,
  DocumentPage,
  DocumentReading,
  Evidence,
  ExtractedField,
  ExtractionResult,
  FieldsResult,
  QuestionCitation,
  QuestionResult,
  ReadingBlock,
  ReviewedField,
  ReviewUpdateFields,
} from "@/types/document";

const MAX_FILE_SIZE = 10 * 1024 * 1024;
const ACCEPTED_TYPES = new Set(["application/pdf", "image/png", "image/jpeg"]);
const ACCEPTED_EXTENSIONS = new Set(["pdf", "png", "jpg", "jpeg"]);
const PROCESSING_STATUSES = new Set([
  "UPLOADED",
  "PROCESSING",
  "READY",
  "READY_WITH_WARNINGS",
  "FAILED",
]);
const UNAVAILABLE_ANSWER = "I couldn't find that in this document.";
const MAX_QUESTION_LENGTH = 500;
const MAX_TRANSCRIPT_ENTRIES = 5;
const SUGGESTED_QUESTIONS = [
  "What is the driving licence number?",
  "When does this licence expire?",
  "Which vehicle classes are listed?",
] as const;

type UploadResponse = {
  document: Document;
  capabilityToken?: string;
};
type DocumentCredential = {
  kind: "authorization" | "document-capability";
  value: string;
};
type StoredDocument = {
  document: Document;
  credential: DocumentCredential;
  previewUrl: string;
};
type PendingCleanup = Pick<StoredDocument, "document" | "credential">;
type WorkspaceOperation = "upload" | "read" | "save" | "remove" | "cleanup";
type SelectedSource = {
  pageNumber: number;
  blockId: string | null;
  sourceText: string;
};
type ReviewTextKey =
  | "full_name"
  | "licence_number"
  | "date_of_birth"
  | "date_of_issue"
  | "date_of_expiry"
  | "address"
  | "issuing_authority";

const REVIEW_FIELDS: ReadonlyArray<{
  key: ReviewTextKey;
  label: string;
  multiline?: boolean;
}> = [
  { key: "full_name", label: "Full name" },
  { key: "licence_number", label: "Driving licence number" },
  { key: "date_of_birth", label: "Date of birth" },
  { key: "date_of_issue", label: "Date of issue" },
  { key: "date_of_expiry", label: "Expiry date" },
  { key: "address", label: "Address", multiline: true },
  { key: "issuing_authority", label: "Issuing authority" },
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function hasOnlyKeys(
  value: Record<string, unknown>,
  expectedKeys: readonly string[],
): boolean {
  const keys = Object.keys(value);
  return (
    keys.length === expectedKeys.length &&
    keys.every((key) => expectedKeys.includes(key))
  );
}

function isDocument(value: unknown): value is Document {
  return (
    isRecord(value) &&
    typeof value.document_id === "string" &&
    value.document_id.length > 0 &&
    typeof value.filename === "string" &&
    value.filename.length > 0 &&
    typeof value.mime_type === "string" &&
    ACCEPTED_TYPES.has(value.mime_type) &&
    typeof value.size_bytes === "number" &&
    Number.isFinite(value.size_bytes) &&
    value.size_bytes >= 0 &&
    typeof value.status === "string" &&
    PROCESSING_STATUSES.has(value.status) &&
    typeof value.created_at === "string" &&
    (value.page_count === null ||
      (typeof value.page_count === "number" &&
        Number.isInteger(value.page_count) &&
        value.page_count > 0)) &&
    Array.isArray(value.warnings) &&
    value.warnings.every((warning) => typeof warning === "string")
  );
}

/** Copy only the public document contract so response-only credentials cannot linger. */
function documentFromResponse(value: Document): Document {
  return {
    document_id: value.document_id,
    filename: value.filename,
    mime_type: value.mime_type,
    size_bytes: value.size_bytes,
    status: value.status,
    created_at: value.created_at,
    page_count: value.page_count,
    warnings: [...value.warnings],
  };
}

function uploadError(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "Something went wrong. Please try again.";
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isUnitInterval(value: unknown): value is number {
  return isFiniteNumber(value) && value >= 0 && value <= 1;
}

function isIsoTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    !Number.isNaN(Date.parse(value))
  );
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isEvidence(value: unknown, documentId: string): value is Evidence {
  if (
    !isRecord(value) ||
    value.document_id !== documentId ||
    typeof value.page_number !== "number" ||
    !Number.isInteger(value.page_number) ||
    value.page_number < 1 ||
    typeof value.source_text !== "string" ||
    (value.block_id !== null &&
      (typeof value.block_id !== "string" || value.block_id.length === 0)) ||
    (value.confidence !== null && !isUnitInterval(value.confidence))
  ) {
    return false;
  }
  if (value.bounding_box === null) return true;
  if (
    !Array.isArray(value.bounding_box) ||
    value.bounding_box.length !== 4 ||
    !value.bounding_box.every(isUnitInterval)
  ) {
    return false;
  }
  const [left, top, right, bottom] = value.bounding_box;
  return left <= right && top <= bottom;
}

function isExtractedField(
  value: unknown,
  documentId: string,
): value is ExtractedField {
  return (
    isRecord(value) &&
    isNullableString(value.value) &&
    isNullableString(value.raw_value) &&
    Array.isArray(value.evidence) &&
    value.evidence.every((item) => isEvidence(item, documentId)) &&
    value.current_value === null &&
    value.is_edited === false &&
    Array.isArray(value.warnings) &&
    value.warnings.every((warning) => typeof warning === "string")
  );
}

function decodeExtraction(
  value: unknown,
  documentId: string,
): ExtractionResult {
  if (!isRecord(value) || !isRecord(value.licence)) {
    throw new ApiError(
      "The backend returned an unexpected extraction.",
      "INVALID_RESPONSE",
    );
  }
  const licence = value.licence;
  if (
    value.document_id !== documentId ||
    (value.status !== "EXTRACTED" &&
      value.status !== "EXTRACTED_WITH_WARNINGS") ||
    licence.document_id !== documentId ||
    !REVIEW_FIELDS.every(({ key }) =>
      isExtractedField(licence[key], documentId),
    ) ||
    !Array.isArray(licence.vehicle_classes) ||
    !licence.vehicle_classes.every((item) =>
      isExtractedField(item, documentId),
    ) ||
    !isRecord(licence.other_information) ||
    !Object.values(licence.other_information).every((item) =>
      isExtractedField(item, documentId),
    ) ||
    !Array.isArray(value.warnings) ||
    !value.warnings.every((warning) => typeof warning === "string") ||
    !isIsoTimestamp(value.created_at)
  ) {
    throw new ApiError(
      "The backend returned an unexpected extraction.",
      "INVALID_RESPONSE",
    );
  }
  return value as unknown as ExtractionResult;
}

function isReviewedField(value: unknown): value is ReviewedField {
  return (
    isRecord(value) &&
    isNullableString(value.current_value) &&
    typeof value.is_edited === "boolean"
  );
}

function decodeFields(value: unknown, documentId: string): FieldsResult {
  if (!isRecord(value) || !isRecord(value.reviewed)) {
    throw new ApiError(
      "The backend returned an unexpected review response.",
      "INVALID_RESPONSE",
    );
  }
  const reviewed = value.reviewed;
  if (
    value.document_id !== documentId ||
    reviewed.document_id !== documentId ||
    !REVIEW_FIELDS.every(({ key }) => isReviewedField(reviewed[key])) ||
    !isRecord(reviewed.vehicle_classes) ||
    !Array.isArray(reviewed.vehicle_classes.current_value) ||
    !reviewed.vehicle_classes.current_value.every(
      (item) => typeof item === "string" && item.length > 0,
    ) ||
    typeof reviewed.vehicle_classes.is_edited !== "boolean" ||
    !isRecord(reviewed.other_information) ||
    !Object.values(reviewed.other_information).every(isReviewedField) ||
    (value.updated_at !== null && !isIsoTimestamp(value.updated_at))
  ) {
    throw new ApiError(
      "The backend returned an unexpected review response.",
      "INVALID_RESPONSE",
    );
  }
  const extraction = decodeExtraction(value.extraction, documentId);
  const sourceKeys = Object.keys(extraction.licence.other_information).sort();
  const reviewedKeys = Object.keys(reviewed.other_information).sort();
  if (
    sourceKeys.length !== reviewedKeys.length ||
    sourceKeys.some((key, index) => key !== reviewedKeys[index])
  ) {
    throw new ApiError(
      "The backend returned mismatched additional information.",
      "INVALID_RESPONSE",
    );
  }
  return { ...value, extraction } as unknown as FieldsResult;
}

function reviewDraft(fields: FieldsResult): ReviewUpdateFields {
  const reviewed = fields.reviewed;
  return {
    full_name: reviewed.full_name.current_value,
    licence_number: reviewed.licence_number.current_value,
    date_of_birth: reviewed.date_of_birth.current_value,
    date_of_issue: reviewed.date_of_issue.current_value,
    date_of_expiry: reviewed.date_of_expiry.current_value,
    address: reviewed.address.current_value,
    vehicle_classes: [...reviewed.vehicle_classes.current_value],
    issuing_authority: reviewed.issuing_authority.current_value,
    other_information: Object.fromEntries(
      Object.entries(reviewed.other_information).map(([key, field]) => [
        key,
        field.current_value,
      ]),
    ),
  };
}

function draftSignature(value: ReviewUpdateFields): string {
  return JSON.stringify(value);
}

function inputValue(value: string | null): string {
  return value ?? "";
}

function savedText(value: string): string | null {
  return value.trim() === "" ? null : value;
}

function isReadingBlock(
  value: unknown,
  documentId: string,
  pageNumber: number,
): value is ReadingBlock {
  if (
    !isRecord(value) ||
    value.document_id !== documentId ||
    value.page_number !== pageNumber ||
    typeof value.source_text !== "string" ||
    typeof value.block_id !== "string" ||
    value.block_id.length === 0 ||
    (value.confidence !== null && !isUnitInterval(value.confidence))
  ) {
    return false;
  }
  if (value.bounding_box === null) return true;
  if (
    !Array.isArray(value.bounding_box) ||
    value.bounding_box.length !== 4 ||
    !value.bounding_box.every(isUnitInterval)
  ) {
    return false;
  }
  const [left, top, right, bottom] = value.bounding_box;
  return left <= right && top <= bottom;
}

function isReadingPage(
  value: unknown,
  documentId: string,
  expectedPageNumber: number,
): value is DocumentPage {
  return (
    isRecord(value) &&
    value.document_id === documentId &&
    value.page_number === expectedPageNumber &&
    typeof value.text === "string" &&
    (value.method === "native_text" || value.method === "ocr") &&
    Array.isArray(value.blocks) &&
    value.blocks.every((block) =>
      isReadingBlock(block, documentId, expectedPageNumber),
    ) &&
    new Set(value.blocks.map((block) => (block as ReadingBlock).block_id))
      .size === value.blocks.length
  );
}

function decodeReading(value: unknown, document: Document): DocumentReading {
  const documentId = document.document_id;
  if (
    !isRecord(value) ||
    value.document_id !== documentId ||
    (value.status !== "READ" && value.status !== "READ_WITH_WARNINGS") ||
    !Array.isArray(value.pages) ||
    value.pages.length === 0 ||
    (document.page_count !== null &&
      value.pages.length !== document.page_count) ||
    !Array.isArray(value.warnings) ||
    !value.warnings.every((warning) => typeof warning === "string") ||
    !isIsoTimestamp(value.created_at) ||
    !value.pages.every((page, index) =>
      isReadingPage(page, documentId, index + 1),
    )
  ) {
    throw new ApiError(
      "The backend returned an unexpected document reading.",
      "INVALID_RESPONSE",
    );
  }
  // The checks above validate the complete untrusted response before this cast.
  return value as unknown as DocumentReading;
}

function isQuestionCitation(value: unknown): value is QuestionCitation {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["block_id", "page_number"]) &&
    typeof value.block_id === "string" &&
    value.block_id.trim().length > 0 &&
    typeof value.page_number === "number" &&
    Number.isInteger(value.page_number) &&
    value.page_number >= 1
  );
}

function citationKey(citation: QuestionCitation): string {
  return JSON.stringify([citation.page_number, citation.block_id]);
}

function readingBlockFor(
  reading: DocumentReading,
  pageNumber: number,
  blockId: string,
): ReadingBlock | null {
  const page = reading.pages.find((item) => item.page_number === pageNumber);
  return page?.blocks.find((block) => block.block_id === blockId) ?? null;
}

function sourceResolves(
  reading: DocumentReading,
  source: SelectedSource,
): boolean {
  const page = reading.pages.find(
    (item) => item.page_number === source.pageNumber,
  );
  if (!page) return false;
  return source.blockId === null
    ? true
    : page.blocks.some((block) => block.block_id === source.blockId);
}

function fieldSources(
  fields: ExtractedField[],
  reading: DocumentReading | null,
): SelectedSource[] {
  if (!reading) return [];
  const sourcesByPage = new Map<number, SelectedSource>();
  for (const evidence of fields.flatMap((field) => field.evidence)) {
    const source: SelectedSource = {
      pageNumber: evidence.page_number,
      blockId: evidence.block_id,
      sourceText: evidence.source_text,
    };
    if (
      !sourcesByPage.has(source.pageNumber) &&
      sourceResolves(reading, source)
    ) {
      sourcesByPage.set(source.pageNumber, source);
    }
  }
  return [...sourcesByPage.values()];
}

function citationSources(
  citations: QuestionCitation[],
  reading: DocumentReading | null,
): SelectedSource[] {
  if (!reading) return [];
  const sourcesByPage = new Map<number, SelectedSource>();
  for (const citation of citations) {
    if (sourcesByPage.has(citation.page_number)) continue;
    const block = readingBlockFor(
      reading,
      citation.page_number,
      citation.block_id,
    );
    if (block) {
      sourcesByPage.set(citation.page_number, {
        pageNumber: citation.page_number,
        blockId: citation.block_id,
        sourceText: block.source_text,
      });
    }
  }
  return [...sourcesByPage.values()];
}

function decodeQuestionResult(
  value: unknown,
  documentId: string,
  question: string,
  reading: DocumentReading,
): QuestionResult {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "document_id",
      "question",
      "status",
      "answer",
      "citations",
      "created_at",
    ]) ||
    value.document_id !== documentId ||
    value.question !== question ||
    (value.status !== "ANSWERED" && value.status !== "UNAVAILABLE") ||
    typeof value.answer !== "string" ||
    !Array.isArray(value.citations) ||
    !value.citations.every(isQuestionCitation) ||
    !isIsoTimestamp(value.created_at) ||
    (value.status === "ANSWERED" &&
      (value.answer.trim().length === 0 || value.citations.length === 0)) ||
    (value.status === "UNAVAILABLE" &&
      (value.answer !== UNAVAILABLE_ANSWER || value.citations.length !== 0))
  ) {
    throw new ApiError(
      "The backend returned an unexpected question response.",
      "INVALID_RESPONSE",
    );
  }
  const citationKeys = value.citations.map(citationKey);
  const readingBlockKeys = new Set(
    reading.pages.flatMap((page) =>
      page.blocks.flatMap((block) =>
        block.block_id === null
          ? []
          : [
              citationKey({
                block_id: block.block_id,
                page_number: page.page_number,
              }),
            ],
      ),
    ),
  );
  if (
    new Set(citationKeys).size !== citationKeys.length ||
    citationKeys.some((key) => !readingBlockKeys.has(key))
  ) {
    throw new ApiError(
      "The backend returned an unexpected question response.",
      "INVALID_RESPONSE",
    );
  }
  return value as unknown as QuestionResult;
}

function formatBytes(bytes: number): string {
  return `${(bytes / 1024 / 1024).toFixed(bytes >= 1024 * 1024 ? 1 : 2)} MB`;
}

function validateFile(file: File): string | null {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!file.name || file.size === 0)
    return "Choose a non-empty PDF, PNG, or JPG file.";
  if (file.size > MAX_FILE_SIZE) return "Choose a file no larger than 10 MB.";
  if (
    !ACCEPTED_EXTENSIONS.has(extension) ||
    (file.type && !ACCEPTED_TYPES.has(file.type))
  ) {
    return "Choose a PDF, PNG, or JPG file.";
  }
  return null;
}

async function uploadDocument(
  file: File,
  sessionAccessToken: string | null,
  accessMode: WorkspaceAccessMode,
  signal: AbortSignal,
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.set("file", file);
  return request("/api/documents", {
    method: "POST",
    headers: sessionAccessToken
      ? { Authorization: `Bearer ${sessionAccessToken}` }
      : undefined,
    body: formData,
    signal,
    decode: async (response) => {
      const value: unknown = await response.json().catch(() => null);
      if (!isDocument(value) || !isRecord(value)) {
        throw new ApiError(
          "The backend returned an unexpected upload response.",
          "INVALID_RESPONSE",
        );
      }
      if (accessMode !== "jwt") {
        if (
          typeof value.access_token !== "string" ||
          value.access_token.length === 0
        ) {
          throw new ApiError(
            "The backend returned an unexpected upload response.",
            "INVALID_RESPONSE",
          );
        }
        return {
          document: documentFromResponse(value),
          capabilityToken: value.access_token,
        };
      }
      return { document: documentFromResponse(value) };
    },
  });
}

function credentialHeaders(credential: DocumentCredential): HeadersInit {
  return credential.kind === "authorization"
    ? { Authorization: `Bearer ${credential.value}` }
    : { "X-Document-Capability": credential.value };
}

async function fetchPreview(
  document: Document,
  credential: DocumentCredential,
  signal: AbortSignal,
): Promise<string> {
  return request(
    `/api/documents/${encodeURIComponent(document.document_id)}/file`,
    {
      headers: { ...credentialHeaders(credential), Accept: document.mime_type },
      signal,
      decode: async (response) => {
        const contentType = response.headers
          .get("content-type")
          ?.split(";", 1)[0];
        if (contentType !== document.mime_type) {
          throw new ApiError(
            "The backend returned an unsupported preview.",
            "INVALID_RESPONSE",
          );
        }
        const blob = await response.blob();
        if (blob.size === 0) {
          throw new ApiError(
            "The backend returned an empty preview.",
            "INVALID_RESPONSE",
          );
        }
        return URL.createObjectURL(new Blob([blob], { type: contentType }));
      },
    },
  );
}

async function deleteDocument(
  documentId: string,
  credential: DocumentCredential,
  signal: AbortSignal,
): Promise<void> {
  await request(`/api/documents/${encodeURIComponent(documentId)}`, {
    method: "DELETE",
    headers: credentialHeaders(credential),
    signal,
    decode: async (response) => {
      if (response.status !== 204) {
        throw new ApiError(
          "The backend returned an unexpected removal response.",
          "INVALID_RESPONSE",
        );
      }
    },
  });
}

async function readDocument(
  document: Document,
  credential: DocumentCredential,
  signal: AbortSignal,
): Promise<DocumentReading> {
  return request(
    `/api/documents/${encodeURIComponent(document.document_id)}/read`,
    {
      method: "POST",
      headers: credentialHeaders(credential),
      signal,
      timeoutMs: 135_000,
      decode: async (response) =>
        decodeReading(await response.json().catch(() => null), document),
    },
  );
}

async function extractDocument(
  documentId: string,
  credential: DocumentCredential,
  signal: AbortSignal,
): Promise<ExtractionResult> {
  return request(`/api/documents/${encodeURIComponent(documentId)}/extract`, {
    method: "POST",
    headers: credentialHeaders(credential),
    signal,
    timeoutMs: 135_000,
    decode: async (response) =>
      decodeExtraction(await response.json().catch(() => null), documentId),
  });
}

async function getFields(
  documentId: string,
  credential: DocumentCredential,
  signal: AbortSignal,
): Promise<FieldsResult> {
  return request(`/api/documents/${encodeURIComponent(documentId)}/fields`, {
    headers: credentialHeaders(credential),
    signal,
    decode: async (response) =>
      decodeFields(await response.json().catch(() => null), documentId),
  });
}

async function putFields(
  documentId: string,
  credential: DocumentCredential,
  fields: ReviewUpdateFields,
  signal: AbortSignal,
): Promise<FieldsResult> {
  return request(`/api/documents/${encodeURIComponent(documentId)}/fields`, {
    method: "PUT",
    headers: {
      ...credentialHeaders(credential),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ fields }),
    signal,
    decode: async (response) =>
      decodeFields(await response.json().catch(() => null), documentId),
  });
}

async function askDocumentQuestion(
  documentId: string,
  credential: DocumentCredential,
  question: string,
  reading: DocumentReading,
  signal: AbortSignal,
): Promise<QuestionResult> {
  return request(`/api/documents/${encodeURIComponent(documentId)}/questions`, {
    method: "POST",
    headers: {
      ...credentialHeaders(credential),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ question }),
    signal,
    timeoutMs: 45_000,
    decode: async (response) =>
      decodeQuestionResult(
        await response.json().catch(() => null),
        documentId,
        question,
        reading,
      ),
  });
}

type DocumentWorkspaceProps = {
  accessMode?: WorkspaceAccessMode;
  sessionAccessToken?: string;
  onUnauthorized?: () => void;
};

/** Owns browser-only authorization and revokes all preview URLs on exit. */
export function DocumentWorkspace({
  accessMode = publicEnv.authMode === "jwt" ? "jwt" : "capability",
  sessionAccessToken,
  onUnauthorized,
}: DocumentWorkspaceProps = {}) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [activeDocument, setActiveDocument] = useState<StoredDocument | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [failedOperation, setFailedOperation] = useState<
    "upload" | "read" | "save" | "remove" | null
  >(null);
  const [reading, setReading] = useState<DocumentReading | null>(null);
  const [fieldsResult, setFieldsResult] = useState<FieldsResult | null>(null);
  const [draft, setDraft] = useState<ReviewUpdateFields | null>(null);
  const [vehicleClassesText, setVehicleClassesText] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [operation, setOperation] = useState<WorkspaceOperation | null>(null);
  const [pendingCleanup, setPendingCleanup] = useState<PendingCleanup | null>(
    null,
  );
  const [question, setQuestion] = useState("");
  const [questionTranscript, setQuestionTranscript] = useState<
    QuestionResult[]
  >([]);
  const [questionError, setQuestionError] = useState<string | null>(null);
  const [questionPending, setQuestionPending] = useState(false);
  const [selectedSource, setSelectedSource] = useState<SelectedSource | null>(
    null,
  );
  const fileInputRef = useRef<HTMLInputElement>(null);
  const questionInputRef = useRef<HTMLInputElement>(null);
  const previewRegionRef = useRef<HTMLDivElement>(null);
  const questionControllerRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const controllersRef = useRef(new Set<AbortController>());
  const previewUrlsRef = useRef(new Set<string>());

  useEffect(() => {
    const controllers = controllersRef.current;
    const previewUrls = previewUrlsRef.current;
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      controllers.forEach((controller) => controller.abort());
      previewUrls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, []);

  const createController = () => {
    const controller = new AbortController();
    controllersRef.current.add(controller);
    return controller;
  };
  const completeController = (controller: AbortController) =>
    controllersRef.current.delete(controller);
  const updateWhenMounted = (update: () => void) => {
    if (mountedRef.current) update();
  };
  const handleUnauthorized = (failure: unknown): boolean => {
    if (
      accessMode === "jwt" &&
      failure instanceof ApiError &&
      failure.status === 401
    ) {
      onUnauthorized?.();
      return true;
    }
    return false;
  };

  const clearQuestionState = () => {
    const questionController = questionControllerRef.current;
    questionControllerRef.current = null;
    questionController?.abort();
    setQuestion("");
    setQuestionTranscript([]);
    setQuestionError(null);
    setQuestionPending(false);
  };

  const focusSource = (source: SelectedSource) => {
    if (!reading || !sourceResolves(reading, source)) return;
    setSelectedSource(source);
    window.requestAnimationFrame(() => {
      previewRegionRef.current?.focus({ preventScroll: true });
      previewRegionRef.current?.scrollIntoView({ block: "start" });
    });
  };

  const renderSourceControls = (fields: ExtractedField[]) => {
    const sources = fieldSources(fields, reading);
    if (sources.length === 0) {
      return (
        <span className="source-unavailable">No source page returned</span>
      );
    }
    return (
      <span className="source-actions">
        {sources.map((source) => (
          <button
            type="button"
            key={`${source.pageNumber}-${source.blockId ?? "page"}`}
            aria-label={`View source on page ${source.pageNumber}`}
            onClick={() => focusSource(source)}
          >
            Source page {source.pageNumber}
          </button>
        ))}
      </span>
    );
  };

  const selectFile = (files: FileList | File[]) => {
    if (operation || pendingCleanup) return;
    setFailedOperation(null);
    if (files.length !== 1) {
      setError("Choose exactly one PDF, PNG, or JPG file.");
      setSelectedFile(null);
      return;
    }
    const file = files[0];
    const validationError = validateFile(file);
    setError(validationError);
    setNotice(null);
    setSelectedFile(validationError ? null : file);
  };

  const onPickerChange = (event: ChangeEvent<HTMLInputElement>) => {
    if (event.target.files) selectFile(event.target.files);
    event.target.value = "";
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
    selectFile(event.dataTransfer.files);
  };

  const attemptCleanup = async (
    cleanup: PendingCleanup,
    replacement?: StoredDocument,
  ) => {
    const controller = createController();
    try {
      await deleteDocument(
        cleanup.document.document_id,
        cleanup.credential,
        controller.signal,
      );
      updateWhenMounted(() => {
        setPendingCleanup((current) =>
          current?.document.document_id === cleanup.document.document_id
            ? null
            : current,
        );
        setNotice(
          replacement
            ? "Your new document is ready."
            : "The incomplete upload was removed.",
        );
      });
    } catch (cleanupFailure) {
      if (handleUnauthorized(cleanupFailure)) return;
      updateWhenMounted(() => {
        if (
          cleanupFailure instanceof ApiError &&
          cleanupFailure.status === 404
        ) {
          setPendingCleanup((current) =>
            current?.document.document_id === cleanup.document.document_id
              ? null
              : current,
          );
          setNotice(
            replacement
              ? "Your new document is ready. The previous temporary document is no longer available."
              : "The incomplete upload is no longer available on the server.",
          );
          return;
        }
        setPendingCleanup(cleanup);
        setNotice(
          replacement
            ? "Your new document is ready, but the previous temporary document could not be removed. Retry cleanup below."
            : "The incomplete upload could not be removed. Retry cleanup below.",
        );
      });
    } finally {
      completeController(controller);
    }
  };

  const submitUpload = async () => {
    if (!selectedFile || operation || pendingCleanup) return;
    if (activeDocument) clearQuestionState();
    setOperation("upload");
    setError(null);
    setFailedOperation(null);
    setNotice(null);
    const controller = createController();
    let previewUrl: string | null = null;
    let uploadedDocument: Pick<
      StoredDocument,
      "document" | "credential"
    > | null = null;
    try {
      const response = await uploadDocument(
        selectedFile,
        sessionAccessToken ?? null,
        accessMode,
        controller.signal,
      );
      const credentialValue =
        accessMode === "jwt" ? sessionAccessToken : response.capabilityToken;
      if (!credentialValue) {
        throw new ApiError(
          "Authentication is required to use this workspace.",
          "AUTH_REQUIRED",
          401,
        );
      }
      const credential: DocumentCredential = {
        kind:
          accessMode === "hybrid-guest"
            ? "document-capability"
            : "authorization",
        value: credentialValue,
      };
      uploadedDocument = {
        document: response.document,
        credential,
      };
      previewUrl = await fetchPreview(
        response.document,
        credential,
        controller.signal,
      );
      previewUrlsRef.current.add(previewUrl);
      const nextDocument: StoredDocument = {
        document: response.document,
        credential,
        previewUrl,
      };
      const previousDocument = activeDocument;
      updateWhenMounted(() => {
        setActiveDocument(nextDocument);
        setSelectedFile(null);
        setSelectedSource(null);
        setReading(null);
        setFieldsResult(null);
        setDraft(null);
        setVehicleClassesText("");
        setNotice(
          previousDocument ? null : "Your document is ready to preview.",
        );
      });
      if (previousDocument) {
        previewUrlsRef.current.delete(previousDocument.previewUrl);
        URL.revokeObjectURL(previousDocument.previewUrl);
        await attemptCleanup(
          {
            document: previousDocument.document,
            credential: previousDocument.credential,
          },
          nextDocument,
        );
      }
    } catch (uploadFailure) {
      if (previewUrl) {
        previewUrlsRef.current.delete(previewUrl);
        URL.revokeObjectURL(previewUrl);
      }
      if (handleUnauthorized(uploadFailure)) return;
      if (uploadedDocument) {
        await attemptCleanup(uploadedDocument);
      }
      const message = uploadError(uploadFailure);
      updateWhenMounted(() => {
        setFailedOperation("upload");
        setError(
          uploadedDocument
            ? `The upload could not be previewed. ${message}`
            : message,
        );
      });
    } finally {
      completeController(controller);
      updateWhenMounted(() => setOperation(null));
    }
  };

  const removeDocument = async () => {
    if (!activeDocument || operation) return;
    clearQuestionState();
    setOperation("remove");
    setError(null);
    setFailedOperation(null);
    const controller = createController();
    try {
      await deleteDocument(
        activeDocument.document.document_id,
        activeDocument.credential,
        controller.signal,
      );
      previewUrlsRef.current.delete(activeDocument.previewUrl);
      URL.revokeObjectURL(activeDocument.previewUrl);
      updateWhenMounted(() => {
        setActiveDocument(null);
        setSelectedSource(null);
        setReading(null);
        setFieldsResult(null);
        setDraft(null);
        setVehicleClassesText("");
        setNotice("Your document was removed.");
      });
    } catch (removeFailure) {
      if (handleUnauthorized(removeFailure)) return;
      if (removeFailure instanceof ApiError && removeFailure.status === 404) {
        previewUrlsRef.current.delete(activeDocument.previewUrl);
        URL.revokeObjectURL(activeDocument.previewUrl);
        updateWhenMounted(() => {
          setActiveDocument(null);
          setSelectedSource(null);
          setReading(null);
          setFieldsResult(null);
          setDraft(null);
          setVehicleClassesText("");
          setNotice("This document is no longer available on the server.");
        });
      } else {
        updateWhenMounted(() => {
          setFailedOperation("remove");
          setError(
            `Your document was not removed. ${uploadError(removeFailure)}`,
          );
        });
      }
    } finally {
      completeController(controller);
      updateWhenMounted(() => setOperation(null));
    }
  };

  const retryCleanup = async () => {
    if (!pendingCleanup || operation) return;
    setOperation("cleanup");
    setError(null);
    await attemptCleanup(pendingCleanup);
    updateWhenMounted(() => setOperation(null));
  };

  const startReading = async () => {
    if (!activeDocument || operation || pendingCleanup || questionPending)
      return;
    const documentId = activeDocument.document.document_id;
    setOperation("read");
    setError(null);
    setFailedOperation(null);
    setNotice(null);
    setSelectedSource(null);
    const controller = createController();
    try {
      const result = await readDocument(
        activeDocument.document,
        activeDocument.credential,
        controller.signal,
      );
      updateWhenMounted(() => {
        if (activeDocument?.document.document_id === documentId) {
          setReading(result);
        }
      });
      await extractDocument(
        documentId,
        activeDocument.credential,
        controller.signal,
      );
      const reviewed = await getFields(
        documentId,
        activeDocument.credential,
        controller.signal,
      );
      updateWhenMounted(() => {
        if (activeDocument?.document.document_id !== documentId) return;
        const nextDraft = reviewDraft(reviewed);
        setFieldsResult(reviewed);
        setDraft(nextDraft);
        setVehicleClassesText(nextDraft.vehicle_classes.join(", "));
        setNotice(
          reviewed.updated_at
            ? "Document review loaded."
            : result.status === "READ_WITH_WARNINGS" ||
                reviewed.extraction.status === "EXTRACTED_WITH_WARNINGS"
              ? "Document processing completed with warnings."
              : "Document review is ready.",
        );
      });
    } catch (readFailure) {
      if (handleUnauthorized(readFailure)) return;
      updateWhenMounted(() => {
        if (activeDocument?.document.document_id !== documentId) return;
        setFailedOperation("read");
        setError(
          `The document could not be fully processed. ${uploadError(readFailure)}`,
        );
      });
    } finally {
      completeController(controller);
      updateWhenMounted(() => setOperation(null));
    }
  };

  const saveChanges = async () => {
    if (!activeDocument || !fieldsResult || !draft || operation) return;
    const documentId = activeDocument.document.document_id;
    const nextFields: ReviewUpdateFields = {
      full_name: savedText(inputValue(draft.full_name)),
      licence_number: savedText(inputValue(draft.licence_number)),
      date_of_birth: savedText(inputValue(draft.date_of_birth)),
      date_of_issue: savedText(inputValue(draft.date_of_issue)),
      date_of_expiry: savedText(inputValue(draft.date_of_expiry)),
      address: savedText(inputValue(draft.address)),
      vehicle_classes: vehicleClassesText
        .split(",")
        .map((value) => value.trim())
        .filter((value) => value.length > 0),
      issuing_authority: savedText(inputValue(draft.issuing_authority)),
      other_information: Object.fromEntries(
        Object.entries(draft.other_information).map(([key, value]) => [
          key,
          savedText(inputValue(value)),
        ]),
      ),
    };
    setOperation("save");
    setError(null);
    setFailedOperation(null);
    setNotice(null);
    const controller = createController();
    try {
      const saved = await putFields(
        documentId,
        activeDocument.credential,
        nextFields,
        controller.signal,
      );
      updateWhenMounted(() => {
        if (activeDocument?.document.document_id !== documentId) return;
        const savedDraft = reviewDraft(saved);
        setFieldsResult(saved);
        setDraft(savedDraft);
        setVehicleClassesText(savedDraft.vehicle_classes.join(", "));
        setNotice("Your review changes were saved.");
      });
    } catch (saveFailure) {
      if (handleUnauthorized(saveFailure)) return;
      updateWhenMounted(() => {
        if (activeDocument?.document.document_id !== documentId) return;
        setFailedOperation("save");
        setError(`Your changes were not saved. ${uploadError(saveFailure)}`);
      });
    } finally {
      completeController(controller);
      updateWhenMounted(() => setOperation(null));
    }
  };

  const resetChanges = () => {
    if (!fieldsResult || operation) return;
    const savedDraft = reviewDraft(fieldsResult);
    setDraft(savedDraft);
    setVehicleClassesText(savedDraft.vehicle_classes.join(", "));
    setError(null);
    setFailedOperation(null);
    setNotice("Unsaved changes were discarded.");
  };

  const submitQuestion = async () => {
    if (
      !activeDocument ||
      !reading ||
      !fieldsResult ||
      questionPending ||
      operation
    )
      return;
    const normalizedQuestion = question.trim();
    if (
      normalizedQuestion.length === 0 ||
      normalizedQuestion.length > MAX_QUESTION_LENGTH
    ) {
      return;
    }
    const documentId = activeDocument.document.document_id;
    const controller = createController();
    questionControllerRef.current = controller;
    setQuestionPending(true);
    setQuestionError(null);
    try {
      const result = await askDocumentQuestion(
        documentId,
        activeDocument.credential,
        normalizedQuestion,
        reading,
        controller.signal,
      );
      updateWhenMounted(() => {
        if (
          questionControllerRef.current !== controller ||
          activeDocument?.document.document_id !== documentId
        ) {
          return;
        }
        setQuestionTranscript((current) =>
          [...current, result].slice(-MAX_TRANSCRIPT_ENTRIES),
        );
        setQuestion("");
      });
    } catch (questionFailure) {
      if (handleUnauthorized(questionFailure)) return;
      updateWhenMounted(() => {
        if (questionControllerRef.current !== controller) return;
        setQuestionError(
          `Your question could not be answered. ${uploadError(questionFailure)}`,
        );
      });
    } finally {
      completeController(controller);
      updateWhenMounted(() => {
        if (questionControllerRef.current !== controller) return;
        questionControllerRef.current = null;
        setQuestionPending(false);
      });
    }
  };

  const busy = operation !== null;
  const chatActionsDisabled = questionPending || busy;
  const uploadBlocked = busy || pendingCleanup !== null;
  const isPdf = activeDocument?.document.mime_type === "application/pdf";
  const savedDraft = fieldsResult ? reviewDraft(fieldsResult) : null;
  const hasUnsavedChanges = Boolean(
    draft &&
    savedDraft &&
    (draftSignature(draft) !== draftSignature(savedDraft) ||
      vehicleClassesText !== savedDraft.vehicle_classes.join(", ")),
  );

  return (
    <div className="workspace-grid">
      <section className="upload-panel" aria-labelledby="document-heading">
        <div className="panel-heading">
          <div className="panel-title">
            <Icon name="document" />
            <h2 id="document-heading">Your document</h2>
          </div>
          <span className="subtle-label">ONE LICENCE AT A TIME</span>
        </div>
        <div
          className={`upload-placeholder ${isDragging ? "is-dragging" : ""}`}
          onDragEnter={(event) => {
            event.preventDefault();
            if (!busy) setIsDragging(true);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={() => setIsDragging(false)}
          onDrop={onDrop}
        >
          {activeDocument ? (
            <div
              ref={previewRegionRef}
              className={`document-preview ${selectedSource ? "is-source-focused" : ""}`}
              role="region"
              aria-label={
                selectedSource
                  ? `Document preview focused on source page ${selectedSource.pageNumber}`
                  : "Document preview"
              }
              tabIndex={-1}
            >
              <div className="preview-heading">
                <strong>{activeDocument.document.filename}</strong>
                <span>{formatBytes(activeDocument.document.size_bytes)}</span>
              </div>
              {isPdf ? (
                <iframe
                  className="pdf-preview"
                  title={`Preview of ${activeDocument.document.filename}`}
                  src={`${activeDocument.previewUrl}${
                    selectedSource ? `#page=${selectedSource.pageNumber}` : ""
                  }`}
                />
              ) : (
                // A private blob URL cannot be optimized by Next's remote image loader.
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  className="image-preview"
                  src={activeDocument.previewUrl}
                  alt={`Preview of ${activeDocument.document.filename}`}
                />
              )}
              {isPdf && (
                <a
                  className="preview-link"
                  href={`${activeDocument.previewUrl}${
                    selectedSource ? `#page=${selectedSource.pageNumber}` : ""
                  }`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open PDF preview
                </a>
              )}
              {selectedSource && (
                <section
                  className="source-evidence-panel"
                  aria-labelledby="source-evidence-heading"
                >
                  <div className="source-evidence-heading">
                    <div>
                      <h3 id="source-evidence-heading">Source evidence</h3>
                      <span>Page {selectedSource.pageNumber}</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => setSelectedSource(null)}
                    >
                      Clear source focus
                    </button>
                  </div>
                  <p>
                    {selectedSource.sourceText ||
                      "No source excerpt was returned."}
                  </p>
                </section>
              )}
            </div>
          ) : (
            <>
              <div className="document-illustration" aria-hidden="true">
                <div className="illustration-back" />
                <div className="illustration-front">
                  <div className="illustration-top">
                    <span />
                    <span />
                    <span />
                  </div>
                  <div className="illustration-content">
                    <div className="illustration-avatar" />
                    <div className="illustration-lines">
                      <i />
                      <i />
                      <i />
                    </div>
                  </div>
                  <div className="illustration-bottom">
                    <i />
                    <i />
                  </div>
                </div>
                <span className="illustration-badge">
                  <Icon name="upload" width="20" height="20" />
                </span>
              </div>
              <h3>
                {selectedFile
                  ? "Ready when you are."
                  : "A little less paperwork."}
              </h3>
              <p>
                {selectedFile ? (
                  "Check the selected file, then upload it."
                ) : (
                  <>
                    Drop a clear licence here or choose it from your device.
                    <br />
                    Clear, readable copies work best.
                  </>
                )}
              </p>
            </>
          )}
          {selectedFile && (
            <p className="selected-file">
              <strong>{selectedFile.name}</strong>
              <span>{formatBytes(selectedFile.size)}</span>
            </p>
          )}
          <input
            ref={fileInputRef}
            className="sr-only"
            id="document-file"
            type="file"
            accept="application/pdf,image/png,image/jpeg,.pdf,.png,.jpg,.jpeg"
            onChange={onPickerChange}
            aria-label="Choose a document file"
            disabled={uploadBlocked}
          />
          <div className="upload-actions">
            <button
              type="button"
              className="upload-button"
              disabled={uploadBlocked}
              onClick={() => fileInputRef.current?.click()}
            >
              <Icon name="upload" width="18" height="18" />
              {activeDocument ? "Choose replacement" : "Choose a document"}
            </button>
            {selectedFile && (
              <button
                type="button"
                className="secondary-button"
                disabled={uploadBlocked}
                onClick={submitUpload}
              >
                {operation === "upload"
                  ? "Uploading…"
                  : activeDocument
                    ? "Replace document"
                    : "Upload document"}
              </button>
            )}
            {activeDocument && (
              <button
                type="button"
                className="secondary-button read-button"
                disabled={
                  busy ||
                  questionPending ||
                  pendingCleanup !== null ||
                  hasUnsavedChanges
                }
                title={
                  hasUnsavedChanges
                    ? "Save or reset your changes before reading again."
                    : undefined
                }
                onClick={startReading}
              >
                {operation === "read"
                  ? "Reading and extracting…"
                  : fieldsResult
                    ? "Read document again"
                    : "Read document"}
              </button>
            )}
            {activeDocument && (
              <button
                type="button"
                className="text-button danger-button"
                disabled={busy}
                onClick={removeDocument}
              >
                {operation === "remove" ? "Removing…" : "Remove document"}
              </button>
            )}
          </div>
          <p className="file-types">
            PDF, PNG or JPG <span>·</span> Up to 10 MB
          </p>
          <p className="retention-copy">
            Image and scanned-page reading uses OpenAI. Uploaded files expire
            after 24 hours, and Remove deletes the server copy.
          </p>
          {error && (
            <p className="operation-message error-message" role="alert">
              {error}
              {!pendingCleanup && (
                <>
                  {" "}
                  <button
                    type="button"
                    className="inline-retry"
                    disabled={busy}
                    onClick={
                      failedOperation === "read"
                        ? startReading
                        : failedOperation === "save"
                          ? saveChanges
                          : failedOperation === "remove"
                            ? removeDocument
                            : selectedFile
                              ? submitUpload
                              : () => fileInputRef.current?.click()
                    }
                  >
                    Try again
                  </button>
                </>
              )}
            </p>
          )}
          {notice && (
            <p className="operation-message" role="status">
              {notice}
            </p>
          )}
          {pendingCleanup && (
            <button
              type="button"
              className="secondary-button cleanup-button"
              disabled={busy}
              onClick={retryCleanup}
            >
              {operation === "cleanup" ? "Cleaning up…" : "Retry cleanup"}
            </button>
          )}
        </div>
        <div className="panel-footnote">
          <span className={`small-dot ${activeDocument ? "is-ready" : ""}`} />
          {activeDocument
            ? operation === "read"
              ? "Reading and extracting document"
              : fieldsResult
                ? "Document review is ready"
                : reading
                  ? "Document reading is ready; extraction needs attention"
                  : "Document ready to preview"
            : "No document added yet"}
        </div>
      </section>

      <section className="details-panel" aria-labelledby="details-heading">
        <div className="panel-heading">
          <div className="panel-title">
            <Icon name="review" />
            <h2 id="details-heading">Extracted information</h2>
          </div>
          <span className="waiting-badge">
            {operation === "read"
              ? "Processing document"
              : operation === "save"
                ? "Saving changes"
                : hasUnsavedChanges
                  ? "Unsaved changes"
                  : fieldsResult?.updated_at
                    ? "Review saved"
                    : fieldsResult
                      ? "Ready to review"
                      : reading?.status === "READ_WITH_WARNINGS"
                        ? "Read with warnings"
                        : reading
                          ? "Reading complete"
                          : activeDocument
                            ? "Ready to read"
                            : "Waiting for a document"}
          </span>
        </div>
        <div className="details-content">
          <p className="details-intro">
            {operation === "read"
              ? "Reading pages, extracting licence details and loading the review. Keep this workspace open."
              : fieldsResult
                ? "Compare each reviewer value with the immutable document extraction before saving."
                : reading
                  ? "Page text is ready, but the review could not be loaded. Retry the document action."
                  : activeDocument
                    ? "Preview is ready. Read the document when you are ready."
                    : "The important details, together."}
          </p>
          {fieldsResult && draft ? (
            <form
              className="review-form"
              onSubmit={(event) => {
                event.preventDefault();
                void saveChanges();
              }}
            >
              <div className="review-fields">
                {REVIEW_FIELDS.map(({ key, label, multiline }) => {
                  const source = fieldsResult.extraction.licence[key];
                  const reviewed = fieldsResult.reviewed[key];
                  const locallyEdited =
                    inputValue(draft[key]) !==
                    inputValue(reviewed.current_value);
                  const sourceId = `${key}-source`;
                  return (
                    <div
                      className={`review-field ${multiline ? "review-field-wide" : ""}`}
                      key={key}
                    >
                      <div className="review-label-row">
                        <label htmlFor={key}>{label}</label>
                        {(reviewed.is_edited || locallyEdited) && (
                          <span className="edited-badge">User-edited</span>
                        )}
                      </div>
                      {multiline ? (
                        <textarea
                          id={key}
                          value={inputValue(draft[key])}
                          aria-describedby={sourceId}
                          disabled={busy}
                          rows={3}
                          onChange={(event) =>
                            setDraft((current) =>
                              current
                                ? { ...current, [key]: event.target.value }
                                : current,
                            )
                          }
                        />
                      ) : (
                        <input
                          id={key}
                          type="text"
                          value={inputValue(draft[key])}
                          aria-describedby={sourceId}
                          disabled={busy}
                          onChange={(event) =>
                            setDraft((current) =>
                              current
                                ? { ...current, [key]: event.target.value }
                                : current,
                            )
                          }
                        />
                      )}
                      <div className="source-comparison" id={sourceId}>
                        <span>
                          Document extraction:{" "}
                          {source.value ?? "No value extracted"}
                        </span>
                        {renderSourceControls([source])}
                      </div>
                      {source.warnings.length > 0 && (
                        <ul className="field-warnings">
                          {source.warnings.map((warning, index) => (
                            <li key={`${key}-${index}-${warning}`}>
                              {warning}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  );
                })}
                <div className="review-field review-field-wide">
                  <div className="review-label-row">
                    <label htmlFor="vehicle_classes">Vehicle classes</label>
                    {(fieldsResult.reviewed.vehicle_classes.is_edited ||
                      vehicleClassesText !==
                        fieldsResult.reviewed.vehicle_classes.current_value.join(
                          ", ",
                        )) && <span className="edited-badge">User-edited</span>}
                  </div>
                  <input
                    id="vehicle_classes"
                    type="text"
                    value={vehicleClassesText}
                    aria-describedby="vehicle-classes-help vehicle-classes-source"
                    disabled={busy}
                    onChange={(event) =>
                      setVehicleClassesText(event.target.value)
                    }
                  />
                  <span className="input-help" id="vehicle-classes-help">
                    Separate multiple classes with commas.
                  </span>
                  <div
                    className="source-comparison"
                    id="vehicle-classes-source"
                  >
                    <span>
                      Document extraction:{" "}
                      {fieldsResult.extraction.licence.vehicle_classes
                        .map((field) => field.value)
                        .filter((value): value is string => value !== null)
                        .join(", ") || "No value extracted"}
                    </span>
                    {renderSourceControls(
                      fieldsResult.extraction.licence.vehicle_classes,
                    )}
                  </div>
                </div>
              </div>
              {Object.keys(fieldsResult.reviewed.other_information).length >
                0 && (
                <fieldset className="additional-fields">
                  <legend>Additional information</legend>
                  {Object.entries(fieldsResult.reviewed.other_information).map(
                    ([key, reviewed], index) => {
                      const source =
                        fieldsResult.extraction.licence.other_information[key];
                      const inputId = `additional-${index}`;
                      const sourceId = `${inputId}-source`;
                      const locallyEdited =
                        inputValue(draft.other_information[key]) !==
                        inputValue(reviewed.current_value);
                      return (
                        <div className="review-field" key={key}>
                          <div className="review-label-row">
                            <label htmlFor={inputId}>{key}</label>
                            {(reviewed.is_edited || locallyEdited) && (
                              <span className="edited-badge">User-edited</span>
                            )}
                          </div>
                          <input
                            id={inputId}
                            type="text"
                            value={inputValue(draft.other_information[key])}
                            aria-describedby={sourceId}
                            disabled={busy}
                            onChange={(event) =>
                              setDraft((current) =>
                                current
                                  ? {
                                      ...current,
                                      other_information: {
                                        ...current.other_information,
                                        [key]: event.target.value,
                                      },
                                    }
                                  : current,
                              )
                            }
                          />
                          <div className="source-comparison" id={sourceId}>
                            <span>
                              Document extraction:{" "}
                              {source.value ?? "No value extracted"}
                            </span>
                            {renderSourceControls([source])}
                          </div>
                          {source.warnings.length > 0 && (
                            <ul className="field-warnings">
                              {source.warnings.map((warning, warningIndex) => (
                                <li key={`${index}-${warningIndex}-${warning}`}>
                                  {warning}
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                      );
                    },
                  )}
                </fieldset>
              )}
              <div className="review-actions">
                <button
                  type="submit"
                  className="upload-button save-button"
                  disabled={!hasUnsavedChanges || busy}
                >
                  {operation === "save" ? "Saving…" : "Save changes"}
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={!hasUnsavedChanges || busy}
                  onClick={resetChanges}
                >
                  Reset unsaved changes
                </button>
                <span className="save-state" role="status">
                  {hasUnsavedChanges
                    ? "Unsaved changes"
                    : fieldsResult.updated_at
                      ? "All changes saved"
                      : "No changes to save"}
                </span>
              </div>
            </form>
          ) : (
            <dl className="field-preview">
              {[
                "Full name",
                "Driving licence number",
                "Date of birth",
                "Expiry date",
                "Vehicle classes",
              ].map((label) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>
                    <span aria-hidden="true">—</span>
                    <span className="sr-only">Not processed</span>
                  </dd>
                </div>
              ))}
            </dl>
          )}
          <div className="evidence-note">
            <Icon name="source" width="18" height="18" />
            <p>
              Keep the source in sight.
              <br />
              <span>
                {fieldsResult
                  ? "Document extraction and page references stay unchanged when reviewer values are saved."
                  : reading
                    ? "Reading keeps page-level source evidence. Complete extraction to review fields."
                    : "Reading is optional and only starts when you choose it."}
              </span>
            </p>
          </div>
          {reading && reading.warnings.length > 0 && (
            <div className="reading-warnings" role="status">
              <strong>Reading warnings</strong>
              <ul>
                {reading.warnings.map((warning, index) => (
                  <li key={`${index}-${warning}`}>{warning}</li>
                ))}
              </ul>
            </div>
          )}
          {fieldsResult && fieldsResult.extraction.warnings.length > 0 && (
            <div className="reading-warnings" role="status">
              <strong>Extraction warnings</strong>
              <ul>
                {fieldsResult.extraction.warnings.map((warning, index) => (
                  <li key={`extraction-${index}-${warning}`}>{warning}</li>
                ))}
              </ul>
            </div>
          )}
          {publicEnv.showDevelopmentStatus && reading && (
            <details className="reading-inspector">
              <summary>Developer page text inspector</summary>
              {reading.pages.map((page) => (
                <section key={page.page_number}>
                  <h3>
                    Page {page.page_number} <span>{page.method}</span>
                  </h3>
                  <pre>{page.text}</pre>
                </section>
              ))}
            </details>
          )}
        </div>
        <section
          className={`chat-preview ${fieldsResult ? "chat-ready" : ""}`}
          aria-labelledby="document-chat-heading"
          aria-busy={questionPending}
        >
          <div className="chat-heading">
            <span className="chat-icon" aria-hidden="true">
              <Icon name="chat" width="20" height="20" />
            </span>
            <div>
              <h3 id="document-chat-heading">Ask this document</h3>
              <p>
                {fieldsResult
                  ? "Answers use the original uploaded document, not saved reviewer corrections."
                  : "Available after reading, extraction and fields are ready."}
              </p>
            </div>
          </div>
          {fieldsResult && activeDocument && (
            <div className="chat-content">
              {(questionTranscript.length > 0 || questionPending) && (
                <ol className="chat-transcript" aria-live="polite">
                  {questionTranscript.map((entry, index) => (
                    <li key={`${entry.created_at}-${index}`}>
                      <p className="chat-question">{entry.question}</p>
                      <div
                        className={`chat-answer ${
                          entry.status === "UNAVAILABLE"
                            ? "chat-answer-unavailable"
                            : ""
                        }`}
                      >
                        <p>{entry.answer}</p>
                        {entry.status === "ANSWERED" &&
                          citationSources(entry.citations, reading).length >
                            0 && (
                            <div
                              className="source-chips"
                              aria-label="Answer sources"
                            >
                              {citationSources(entry.citations, reading).map(
                                (source) => (
                                  <button
                                    type="button"
                                    key={`${source.pageNumber}-${source.blockId}`}
                                    aria-label={`View source on page ${source.pageNumber}`}
                                    onClick={() => focusSource(source)}
                                  >
                                    Source page {source.pageNumber}
                                  </button>
                                ),
                              )}
                            </div>
                          )}
                      </div>
                    </li>
                  ))}
                  {questionPending && (
                    <li className="chat-pending" role="status">
                      Looking in this document…
                    </li>
                  )}
                </ol>
              )}
              <div
                className="suggested-questions"
                aria-labelledby="suggested-questions-label"
              >
                <span id="suggested-questions-label">Suggested questions</span>
                <div>
                  {SUGGESTED_QUESTIONS.map((suggestion) => (
                    <button
                      type="button"
                      key={suggestion}
                      disabled={chatActionsDisabled}
                      onClick={() => {
                        setQuestion(suggestion);
                        setQuestionError(null);
                        questionInputRef.current?.focus();
                      }}
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
              <form
                className="question-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  void submitQuestion();
                }}
              >
                <label htmlFor="document-question">Your question</label>
                <div>
                  <input
                    ref={questionInputRef}
                    id="document-question"
                    name="question"
                    type="text"
                    value={question}
                    maxLength={MAX_QUESTION_LENGTH}
                    autoComplete="off"
                    required
                    disabled={chatActionsDisabled}
                    aria-describedby={
                      questionError ? "question-error" : undefined
                    }
                    onChange={(event) => {
                      setQuestion(event.target.value);
                      setQuestionError(null);
                    }}
                  />
                  <button
                    type="submit"
                    disabled={
                      chatActionsDisabled || question.trim().length === 0
                    }
                  >
                    {questionPending ? "Asking…" : "Ask"}
                  </button>
                </div>
                {questionError && (
                  <p
                    id="question-error"
                    className="question-error"
                    role="alert"
                  >
                    {questionError}
                  </p>
                )}
              </form>
            </div>
          )}
        </section>
      </section>
    </div>
  );
}
