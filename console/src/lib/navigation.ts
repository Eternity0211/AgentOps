import type { SessionPrincipal } from "./session";

export interface NavigationItem {
  label: string;
  href: string;
  permission: string | null;
}

const navigation: readonly NavigationItem[] = [
  { label: "Overview", href: "/", permission: null },
  { label: "Incidents", href: "/incidents", permission: "incident:read" },
  {
    label: "Operations",
    href: "/operations",
    permission: "approved_action:execute",
  },
  { label: "Approvals", href: "/approvals", permission: "approval:decide" },
  { label: "Audit", href: "/audit", permission: "audit:read" },
  { label: "Administration", href: "/admin", permission: "admin:manage" },
];

export function navigationFor(principal: SessionPrincipal): NavigationItem[] {
  const granted = new Set(principal.permissions);
  return navigation.filter(
    (item) => item.permission === null || granted.has(item.permission),
  );
}

export function isActivePath(pathname: string, href: string): boolean {
  return href === "/"
    ? pathname === href
    : pathname === href || pathname.startsWith(`${href}/`);
}
