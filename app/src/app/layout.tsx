import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "FurnitureOS",
  description: "Furnish your apartment before you move in.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
