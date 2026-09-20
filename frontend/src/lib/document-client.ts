import { ApiError, request } from "@/lib/api-client";
import {
  ProcessingStatus,
  type ChatHistoryResponse,
  type Document,
  type DocumentListResponse,
  type QuestionCitation,
  type QuestionResult,
} from "@/types/document";

const DOCUMENT_KEYS = [
  "document_id",
  "filename",
  "mime_type",
  "size_bytes",
  "status",
  "created_at",
  "page_count",
  "warnings",
] as const;
const QUESTION_KEYS = [
  "document_id",
  "question",
  "status",
  "answer",
  "citations",
  "created_at",
] as const;
const MIME_TYPES = new Set(["application/pdf", "image/png", "image/jpeg"]);
const PROCESSING_STATUSES = new Set(Object.values(ProcessingStatus));
const UNAVAILABLE_ANSWER = "I couldn't find that in this document.";
const OUT_OF_SCOPE_ANSWER =
  "I’m LicenceIQ, and I can help with questions about the uploaded driving licence. " +
  "Try asking about its holder, licence number, dates, address, issuing authority, " +
  "vehicle classes, or restrictions.";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function hasExactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
): boolean {
  const keys = Object.keys(value);
  return (
    keys.length === expected.length &&
    expected.every((key) => Object.hasOwn(value, key))
  );
}

function isIsoTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    !Number.isNaN(Date.parse(value))
  );
}

function isDocument(value: unknown): value is Document {
  return (
    isRecord(value) &&
    hasExactKeys(value, DOCUMENT_KEYS) &&
    typeof value.document_id === "string" &&
    value.document_id.length > 0 &&
    typeof value.filename === "string" &&
    value.filename.length > 0 &&
    typeof value.mime_type === "string" &&
    MIME_TYPES.has(value.mime_type) &&
    typeof value.size_bytes === "number" &&
    Number.isSafeInteger(value.size_bytes) &&
    value.size_bytes >= 0 &&
    typeof value.status === "string" &&
    PROCESSING_STATUSES.has(value.status as ProcessingStatus) &&
    isIsoTimestamp(value.created_at) &&
    (value.page_count === null ||
      (typeof value.page_count === "number" &&
        Number.isSafeInteger(value.page_count) &&
        value.page_count > 0)) &&
    Array.isArray(value.warnings) &&
    value.warnings.every((warning) => typeof warning === "string")
  );
}

function isQuestionCitation(value: unknown): value is QuestionCitation {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["block_id", "page_number"]) &&
    typeof value.block_id === "string" &&
    value.block_id.trim().length > 0 &&
    typeof value.page_number === "number" &&
    Number.isSafeInteger(value.page_number) &&
    value.page_number >= 1
  );
}

function isQuestionResult(
  value: unknown,
  documentId: string,
): value is QuestionResult {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, QUESTION_KEYS) ||
    value.document_id !== documentId ||
    typeof value.question !== "string" ||
    value.question.trim().length === 0 ||
    value.question.length > 500 ||
    (value.status !== "ANSWERED" &&
      value.status !== "UNAVAILABLE" &&
      value.status !== "OUT_OF_SCOPE") ||
    typeof value.answer !== "string" ||
    !Array.isArray(value.citations) ||
    !value.citations.every(isQuestionCitation) ||
    !isIsoTimestamp(value.created_at)
  ) {
    return false;
  }

  const citationKeys = value.citations.map((citation) =>
    JSON.stringify([citation.page_number, citation.block_id]),
  );
  if (new Set(citationKeys).size !== citationKeys.length) return false;

  return (
    (value.status === "ANSWERED" &&
      value.answer.trim().length > 0 &&
      value.citations.length > 0) ||
    (value.status === "UNAVAILABLE" &&
      value.answer === UNAVAILABLE_ANSWER &&
      value.citations.length === 0) ||
    (value.status === "OUT_OF_SCOPE" &&
      value.answer === OUT_OF_SCOPE_ANSWER &&
      value.citations.length === 0)
  );
}

function authorizationHeaders(accessToken: string): HeadersInit {
  if (!accessToken) {
    throw new ApiError(
      "Authentication is required to load saved documents.",
      "AUTH_REQUIRED",
      401,
    );
  }
  return { Authorization: `Bearer ${accessToken}` };
}

/** List only documents owned by the current authenticated account. */
export function listSavedDocuments(
  accessToken: string,
  signal?: AbortSignal,
): Promise<DocumentListResponse> {
  return request("/api/documents", {
    headers: authorizationHeaders(accessToken),
    signal,
    decode: async (response) => {
      const value: unknown = await response.json().catch(() => null);
      if (
        !isRecord(value) ||
        !hasExactKeys(value, ["documents"]) ||
        !Array.isArray(value.documents) ||
        value.documents.length > 50 ||
        !value.documents.every(isDocument)
      ) {
        throw new ApiError(
          "The backend returned an unexpected saved document list.",
          "INVALID_RESPONSE",
        );
      }
      const documents = value.documents as Document[];
      if (
        new Set(documents.map((document) => document.document_id)).size !==
          documents.length ||
        documents.some(
          (document, index) =>
            index > 0 &&
            Date.parse(documents[index - 1].created_at) <
              Date.parse(document.created_at),
        )
      ) {
        throw new ApiError(
          "The backend returned duplicate saved documents.",
          "INVALID_RESPONSE",
        );
      }
      return { documents: documents.map((document) => ({ ...document })) };
    },
  });
}

/** Load verified persisted turns for one owned authenticated document. */
export function getSavedChatHistory(
  documentId: string,
  accessToken: string,
  signal?: AbortSignal,
): Promise<ChatHistoryResponse> {
  return request(
    `/api/documents/${encodeURIComponent(documentId)}/chat-history`,
    {
      headers: authorizationHeaders(accessToken),
      signal,
      decode: async (response) => {
        const value: unknown = await response.json().catch(() => null);
        if (
          !isRecord(value) ||
          !hasExactKeys(value, ["document_id", "turns"]) ||
          value.document_id !== documentId ||
          !Array.isArray(value.turns) ||
          value.turns.length > 100 ||
          !value.turns.every((turn) => isQuestionResult(turn, documentId))
        ) {
          throw new ApiError(
            "The backend returned an unexpected saved chat history.",
            "INVALID_RESPONSE",
          );
        }
        const turns = value.turns as QuestionResult[];
        if (
          turns.some(
            (turn, index) =>
              index > 0 &&
              Date.parse(turns[index - 1].created_at) >
                Date.parse(turn.created_at),
          )
        ) {
          throw new ApiError(
            "The backend returned an unexpected saved chat order.",
            "INVALID_RESPONSE",
          );
        }
        return {
          document_id: documentId,
          turns: turns.map((turn) => ({
            ...turn,
            citations: turn.citations.map((citation) => ({ ...citation })),
          })),
        };
      },
    },
  );
}

/** Delete the persisted transcript for one owned authenticated document. */
export function deleteSavedChatHistory(
  documentId: string,
  accessToken: string,
  signal?: AbortSignal,
): Promise<void> {
  return request(
    `/api/documents/${encodeURIComponent(documentId)}/chat-history`,
    {
      method: "DELETE",
      headers: authorizationHeaders(accessToken),
      signal,
      decode: async (response) => {
        if (response.status !== 204) {
          throw new ApiError(
            "The backend returned an unexpected clear-history response.",
            "INVALID_RESPONSE",
          );
        }
      },
    },
  );
}
