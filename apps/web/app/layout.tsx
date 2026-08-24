export const metadata = {
  title: "PostMortem AI",
  description: "Evidence-grounded incident postmortem drafting.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", margin: 0, background: "#f7f7f5", color: "#1a1a1a" }}>
        {children}
      </body>
    </html>
  );
}
