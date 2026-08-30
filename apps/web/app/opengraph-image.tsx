import { ImageResponse } from "next/og";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "80px",
          background: "#ffffff",
          color: "#111111",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 40,
              height: 40,
              borderRadius: 9,
              background: "#1a1a1a",
              fontWeight: 700,
              fontSize: 20,
            }}
          >
            <span style={{ color: "#f7f7f5" }}>[</span>
            {/* SVG path, not the ✓ Unicode character -- see icon.tsx's
                comment: Satori has to fetch a font subset for any
                non-ASCII glyph, and that fetch can fail outright (caught
                live during this exact build). A path has no font
                dependency. */}
            <svg width="16" height="16" viewBox="0 0 14 14" style={{ margin: "0 1px" }}>
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
          <div style={{ fontSize: 28, letterSpacing: 4, textTransform: "uppercase", color: "#666666" }}>
            PostMortem AI
          </div>
        </div>
        <div style={{ display: "flex", fontSize: 60, fontWeight: 600, marginTop: 20, lineHeight: 1.15 }}>
          Evidence-grounded
        </div>
        <div style={{ display: "flex", fontSize: 60, fontWeight: 600, lineHeight: 1.15 }}>
          incident postmortems
        </div>
        <div style={{ display: "flex", fontSize: 28, color: "#444444", marginTop: 28, maxWidth: 900 }}>
          Every claim cites real recorded evidence. Unsupported claims are marked, never fabricated.
        </div>
      </div>
    ),
    { ...size },
  );
}
