const DEFAULT_API_BASE_URL = "/api/v1";

export function resolveApiBaseUrl(value: string | undefined): string {
  const candidate = value?.trim() || DEFAULT_API_BASE_URL;
  if (candidate.startsWith("/")) {
    if (
      candidate.startsWith("//") ||
      candidate.includes("#") ||
      candidate.includes("?")
    ) {
      throw new Error(
        "NEXT_PUBLIC_AGENTOPS_API_BASE_URL must be a clean absolute path",
      );
    }
    return candidate === "/" ? candidate : candidate.replace(/\/$/, "");
  }
  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    throw new Error(
      "NEXT_PUBLIC_AGENTOPS_API_BASE_URL must be an HTTP(S) URL or absolute path",
    );
  }
  if (
    !["http:", "https:"].includes(parsed.protocol) ||
    parsed.username ||
    parsed.password ||
    parsed.hash ||
    parsed.search
  ) {
    throw new Error(
      "NEXT_PUBLIC_AGENTOPS_API_BASE_URL contains forbidden URL components",
    );
  }
  return parsed.toString().replace(/\/$/, "");
}

export const consoleConfig = Object.freeze({
  apiBaseUrl: resolveApiBaseUrl(process.env.NEXT_PUBLIC_AGENTOPS_API_BASE_URL),
});
