import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AuthenticatedShell } from "@/components/authenticated-shell";

import "./styles.css";

export const metadata: Metadata = {
  title: "AgentOps Incident Commander",
  description:
    "Evidence-driven incident diagnosis and controlled recovery console",
};

export default function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <AuthenticatedShell>{children}</AuthenticatedShell>
      </body>
    </html>
  );
}
