import type { Metadata } from "next";
import { DM_Sans, Geist, Geist_Mono, Space_Grotesk } from "next/font/google";
import { Analytics } from "@vercel/analytics/next";
import { CookieConsentBanner } from "@/components/cookie-consent";
import { PostHogProvider } from "@/components/posthog-provider";
import "./globals.css";

// Landing-page typography (unchanged from before the redesign).
const dmSans = DM_Sans({
  variable: "--font-dm-sans",
  subsets: ["latin"],
});
const spaceGrotesk = Space_Grotesk({
  variable: "--font-space-grotesk",
  subsets: ["latin"],
  weight: ["400", "500", "700"],
});

// Workspace-scoped typography (Direction B redesign). Consumed by
// `.b-shell` only — see globals.css.
const geist = Geist({
  variable: "--font-geist",
  subsets: ["latin"],
});
const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Job Application Copilot",
  description:
    "Upload your resume, review a role, and generate tailored application documents in one workspace.",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/icon.png", type: "image/png" },
    ],
    apple: [{ url: "/apple-icon.png", sizes: "180x180", type: "image/png" }],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${dmSans.variable} ${spaceGrotesk.variable} ${geist.variable} ${geistMono.variable}`}
      suppressHydrationWarning
    >
      <body>
        <PostHogProvider>{children}</PostHogProvider>
        <CookieConsentBanner />
        <Analytics />
      </body>
    </html>
  );
}
