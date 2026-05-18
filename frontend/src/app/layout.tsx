import type { Metadata } from "next";
import { DM_Sans, Geist_Mono, Space_Grotesk } from "next/font/google";
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
  // 600 (SemiBold) is required: globals.css uses `font-weight: 600`
  // in 60+ rules — every `.b-shell` heading, region title, button and
  // chip via --font-display. Omitting it made the browser substitute
  // the 700 Bold face for all of them, so workspace headings/labels
  // rendered heavier than intended (the "weird font" report). Matches
  // HelpmateAI's load exactly.
  weight: ["400", "500", "600", "700"],
});

// Workspace mono (Direction B redesign). The only Geist face the
// workspace consumes — `.b-shell --font-mono` in globals.css. (The
// Geist *sans* face was loaded but never referenced; dropped.)
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
      className={`${dmSans.variable} ${spaceGrotesk.variable} ${geistMono.variable}`}
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
