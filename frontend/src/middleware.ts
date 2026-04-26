import { NextRequest, NextResponse } from "next/server";

export function middleware(req: NextRequest) {
  const hostname = req.headers.get("host") ?? "";

  if (hostname.startsWith("app.")) {
    const url = req.nextUrl.clone();

    // If someone hits /workspace directly on the app subdomain, redirect to /
    // so the URL stays clean as app.job-application-copilot.xyz
    if (url.pathname === "/workspace") {
      url.pathname = "/";
      return NextResponse.redirect(url);
    }

    // Rewrite / to /workspace content without changing the URL
    if (url.pathname === "/") {
      url.pathname = "/workspace";
      return NextResponse.rewrite(url);
    }
  }

  return NextResponse.next();
}

export const config = {
  // Run on all routes except Next.js internals and static files
  matcher: ["/((?!_next|favicon.ico|.*\\..*).*)"],
};
