import type { ReactNode, SVGProps } from "react";

type IconName = "document" | "upload" | "review" | "chat" | "arrow" | "source";

const paths: Record<IconName, ReactNode> = {
  document: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="3" />
      <circle cx="8" cy="10" r="1.5" />
      <path d="M6 15h4m4-6h4m-4 4h4m-4 3h2" />
    </>
  ),
  upload: (
    <>
      <path d="M12 15V3m-4 4 4-4 4 4M4 14v5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5" />
    </>
  ),
  review: (
    <>
      <path d="M15 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-5-5Z" />
      <path d="M14 3v6h6m-12 5 2 2 5-5" />
    </>
  ),
  chat: (
    <>
      <path d="M21 11a8 8 0 0 1-8 8H6l-4 3V11a9 9 0 0 1 19 0Z" />
      <path d="M7 10h9m-9 4h6" />
    </>
  ),
  arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
  source: (
    <>
      <path d="M9 4H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h13a2 2 0 0 0 2-2v-4M14 3h7v7m0-7L10 14" />
    </>
  ),
};

/** Small decorative icons keep the initial shell independent of a UI library. */
export function Icon({
  name,
  ...props
}: SVGProps<SVGSVGElement> & { name: IconName }) {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {paths[name]}
    </svg>
  );
}
