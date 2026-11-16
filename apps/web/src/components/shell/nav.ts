import {
  Blocks,
  Briefcase,
  LineChart,
  Newspaper,
  Radio,
  Shield,
  Sparkles,
  UserRound,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  description: string;
  shortcut: string;
  admin?: boolean;
  mobile?: boolean;
}

export const NAV: NavItem[] = [
  { href: "/", label: "Copilot", icon: Sparkles, description: "AI research assistant", shortcut: "G H", mobile: true },
  { href: "/build", label: "Build", icon: Blocks, description: "Strategies & backtests", shortcut: "G B", mobile: true },
  { href: "/deployments", label: "Live", icon: Radio, description: "Running strategies", shortcut: "G L" },
  { href: "/analysis", label: "Analysis", icon: LineChart, description: "Dashboards & scanners", shortcut: "G A", mobile: true },
  { href: "/news", label: "News", icon: Newspaper, description: "Markets & announcements", shortcut: "G N" },
  { href: "/portfolio", label: "Portfolio", icon: Briefcase, description: "Holdings & positions", shortcut: "G P", mobile: true },
  { href: "/profile", label: "Profile", icon: UserRound, description: "Account, brokers, billing", shortcut: "G U", mobile: true },
  { href: "/admin", label: "Admin", icon: Shield, description: "Operations console", shortcut: "G X", admin: true },
];
