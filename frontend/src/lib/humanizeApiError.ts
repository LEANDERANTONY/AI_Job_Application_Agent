/**
 * Translate a thrown error into a copy-safe, user-facing string.
 *
 * The backend's `request()` helper in `lib/api.ts` throws Errors whose
 * `.message` is the raw `payload.detail` from the API — for AppError
 * routes that's already a friendly user_message, but several leaky
 * paths surface raw Python exception text or Pydantic validation
 * arrays. The fallback `Request failed with status N` shows up on 5xx
 * responses with no body.
 *
 * This helper centralizes the "weird errors with numbers" cleanup so
 * every notice / banner site renders the same consistent voice.
 *
 * Usage:
 *
 *     setNotice({
 *       level: "warning",
 *       message: humanizeApiError(error, "Workspace analysis failed."),
 *     });
 *
 * The optional second argument is a context-specific fallback used
 * when the input has no extractable message (network drop,
 * non-Error object). When the input DOES carry a message, that
 * message is humanized — the fallback is never used as a prefix or
 * suffix.
 *
 * Pure function — no React imports, no side effects. Trivial to unit
 * test.
 */
const STATUS_MESSAGES: Record<number, string> = {
  400: "That request wasn't quite right. Please review and try again.",
  401: "Please sign in to continue.",
  403: "You don't have access to this. Try signing in again.",
  404: "We couldn't find that. It may have been removed or expired.",
  408: "The request took too long. Please try again.",
  409: "That conflicts with something already in place. Please try again.",
  422: "Some required information is missing or isn't valid. Please review the form and try again.",
  429: "Too many requests right now. Please wait a moment and try again.",
};

const LEAKY_PYTHON_ERROR_PREFIX =
  /^(value|runtime|type|key|index|attribute|lookup|os|io|permission|assertion|name|file|json|unicode|http)\s?error\s*[:(]\s*/i;

const LEAKY_GENERIC_PREFIX = /^(exception|error)\s*[:(]\s*/i;

const PYDANTIC_FIELD_HINT = /\bbody\.[a-z_][a-z0-9_]*\b/i;

const REQUEST_FAILED_PATTERN = /^request failed with status (\d{3})\.?\s*$/i;

const MAX_MESSAGE_LENGTH = 240;

const DEFAULT_FALLBACK =
  "Something went wrong. Please try again in a moment.";

function extractMessage(input: unknown): string {
  if (input instanceof Error) return input.message;
  if (typeof input === "string") return input;
  if (input === null || input === undefined) return "";
  if (typeof input === "object" && "message" in input) {
    const value = (input as { message: unknown }).message;
    if (typeof value === "string") return value;
  }
  return "";
}

function translateStatus(status: number): string {
  if (STATUS_MESSAGES[status]) return STATUS_MESSAGES[status];
  if (status >= 500 && status <= 599) {
    return "Something went wrong on our end. Please try again in a moment.";
  }
  // Other 4xx without an explicit mapping: keep the status visible
  // (the user can report it) but wrap it in friendly framing.
  return `Request failed (status ${status}). Please try again.`;
}

function stripLeakyPrefix(message: string): string {
  let cleaned = message;
  if (LEAKY_PYTHON_ERROR_PREFIX.test(cleaned)) {
    cleaned = cleaned.replace(LEAKY_PYTHON_ERROR_PREFIX, "");
  } else if (LEAKY_GENERIC_PREFIX.test(cleaned)) {
    cleaned = cleaned.replace(LEAKY_GENERIC_PREFIX, "");
  }
  return cleaned.trim();
}

function isPydanticFieldNoise(message: string): boolean {
  // Multiple `body.field msg` clauses joined by ", " is the giveaway.
  // A single AppError user_message that just happens to contain "body."
  // (rare) won't match because there's no comma + second clause.
  return PYDANTIC_FIELD_HINT.test(message) && message.includes(", ");
}

function capLength(message: string): string {
  if (message.length <= MAX_MESSAGE_LENGTH) return message;
  return `${message.slice(0, MAX_MESSAGE_LENGTH - 1).trimEnd()}…`;
}

/**
 * Public entry point. See file header for usage.
 */
export function humanizeApiError(input: unknown, fallback?: string): string {
  const raw = extractMessage(input).trim();
  if (!raw) return fallback ?? DEFAULT_FALLBACK;

  const statusMatch = raw.match(REQUEST_FAILED_PATTERN);
  if (statusMatch) {
    return translateStatus(Number(statusMatch[1]));
  }

  if (isPydanticFieldNoise(raw)) {
    return STATUS_MESSAGES[422];
  }

  const cleaned = stripLeakyPrefix(raw);
  if (!cleaned) return fallback ?? DEFAULT_FALLBACK;

  return capLength(cleaned);
}
