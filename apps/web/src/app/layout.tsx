import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { connection } from "next/server";
import { Providers } from "@/components/providers";
import "./globals.css";
import "./design.css";

const sans = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
});

export const metadata: Metadata = {
  title: "Sales Engine",
  description: "Revenue workspace for AGRAYIAN AI Labs",
  icons: {
    icon: [{ url: "/icon.svg", type: "image/svg+xml" }],
  },
};

export const dynamic = "force-dynamic";

function publicApiUrl(): string {
  const value = process.env.NEXT_PUBLIC_API_URL?.trim().replace(/\/$/, "");
  return value || "http://localhost:8000";
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  await connection();
  const bootstrap = `window.__AGRAYIAN_API_URL=${JSON.stringify(publicApiUrl())};`;
  return (
    <html lang="en-US">
      <body className={`${sans.variable} font-sans antialiased`}>
        <script dangerouslySetInnerHTML={{ __html: bootstrap }} />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
