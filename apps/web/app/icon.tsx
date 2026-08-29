import { ImageResponse } from "next/og";

// No favicon existed anywhere in the project (confirmed live: /favicon.ico
// 404'd, no <link rel="icon"> in the rendered HTML at all) -- every browser
// tab, bookmark, and search result showed a generic blank icon instead of
// this product's own mark. Next.js's icon.tsx file convention generates a
// real one and wires the <link rel="icon"> tag automatically, the same
// ImageResponse approach opengraph-image.tsx already uses.
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
          background: "#111111",
          color: "#ffffff",
          fontFamily: "sans-serif",
          fontSize: 20,
          fontWeight: 700,
          borderRadius: 6,
        }}
      >
        P
      </div>
    ),
    { ...size },
  );
}
