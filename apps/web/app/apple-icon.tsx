import { ImageResponse } from "next/og";

// iOS "Add to Home Screen" bookmarks previously showed a generic
// screenshot-of-the-page thumbnail (no apple-touch-icon existed at all) --
// this file's naming convention is Next.js's own for that exact icon size.
// Same mark as icon.tsx (SVG path checkmark, no font-glyph dependency --
// see that file's comment for why), just rendered at the larger canvas
// Apple expects, with no rounded corners since iOS applies its own mask.
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#1a1a1a",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", fontFamily: "sans-serif", fontWeight: 700, fontSize: 96 }}>
          <span style={{ color: "#f7f7f5" }}>[</span>
          <svg width="78" height="78" viewBox="0 0 14 14" style={{ margin: "0 6px" }}>
            <path
              d="M2.5 7.3L5.5 10.3L11.5 3.7"
              stroke="#2a6e5c"
              strokeWidth="2.4"
              strokeLinecap="round"
              strokeLinejoin="round"
              fill="none"
            />
          </svg>
          <span style={{ color: "#f7f7f5" }}>]</span>
        </div>
      </div>
    ),
    { ...size },
  );
}
