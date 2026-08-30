import { ImageResponse } from "next/og";

// The real product mark, not a placeholder letter -- see logo-mark.tsx for
// the full explanation. The checkmark is drawn as an SVG path, not the ✓
// Unicode character -- an earlier version used the character and the build
// itself caught a real problem: Satori (next/og's renderer) has to fetch a
// font subset for any non-ASCII glyph, and that fetch failed outright
// during a real local build ("Failed to download dynamic font. Status:
// 400"). A path has no font dependency at all, so it can't fail this way
// in any environment. Same ink/paper/accent palette globals.css defines
// for the rest of the app.
export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
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
          borderRadius: 7,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", fontFamily: "sans-serif", fontWeight: 700, fontSize: 17 }}>
          <span style={{ color: "#f7f7f5" }}>[</span>
          <svg width="14" height="14" viewBox="0 0 14 14" style={{ margin: "0 1px" }}>
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
