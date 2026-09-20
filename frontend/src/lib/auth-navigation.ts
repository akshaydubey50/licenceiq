/** Return only a same-origin App Router destination suitable for router.replace. */
export function safeNextDestination(
  value: string | string[] | undefined,
): string {
  const candidate = Array.isArray(value) ? value[0] : value;
  if (!candidate || !candidate.startsWith("/") || candidate.startsWith("//")) {
    return "/";
  }

  try {
    const base = "https://licenceiq.local";
    const parsed = new URL(candidate, base);
    if (parsed.origin !== base) return "/";
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return "/";
  }
}

/** Preserve a validated local destination between authentication pages. */
export function authRouteWithNext(
  route: "/login" | "/signup",
  destination: string,
): string {
  return `${route}?next=${encodeURIComponent(destination)}`;
}
