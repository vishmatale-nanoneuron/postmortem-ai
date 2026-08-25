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
        <div style={{ fontSize: 28, letterSpacing: 4, textTransform: "uppercase", color: "#666666" }}>
          PostMortem AI
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
