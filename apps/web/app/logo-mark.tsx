// The product's real, distinctive visual language -- not a generic
// abstract shape. Every postmortem draft renders evidence as bracketed
// citations ("[1] alert: ...") and every claim is either backed by one of
// those citations or replaced with a fixed unsupported marker. This mark
// is that exact idea, literally: a bracketed checkmark -- "[✓]" -- built
// as three simple paths (bracket, check, bracket) rather than an emoji or
// font glyph, so it renders identically everywhere (browser tab favicon,
// social share image, this component) regardless of what fonts a viewer
// has installed.
export function LogoMark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      role="img"
      aria-label="PostMortem AI"
    >
      <rect width="32" height="32" rx="7" fill="#1a1a1a" />
      {/* Left bracket */}
      <path
        d="M12.5 8.5H10.5C9.94772 8.5 9.5 8.94772 9.5 9.5V22.5C9.5 23.0523 9.94772 23.5 10.5 23.5H12.5"
        stroke="#f7f7f5"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Right bracket */}
      <path
        d="M19.5 8.5H21.5C22.0523 8.5 22.5 8.94772 22.5 9.5V22.5C22.5 23.0523 22.0523 23.5 21.5 23.5H19.5"
        stroke="#f7f7f5"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Checkmark -- the verified claim */}
      <path
        d="M13.2 16.4L15.3 18.6L18.9 13.6"
        stroke="#2a6e5c"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
