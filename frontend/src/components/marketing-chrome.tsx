"use client";

import { ArrowRight, ArrowUpRight, Menu, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useAccount } from "@/components/account-provider";

export function Brand() {
  return <span className="brand"><span className="brand-symbol"><svg viewBox="0 0 28 28" fill="none" aria-hidden="true"><path d="M4 23V11L14 4l10 7v12h-7v-9h-6v9H4Z" stroke="currentColor" strokeWidth="2.1"/><path d="m18 5 6-3v7" stroke="currentColor" strokeWidth="2.1"/></svg></span><span>Sheriff Sale<span className="brand-second">Hunter</span></span></span>;
}

export function Button({ children, className = "", variant = "default", size = "default", ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "outline" | "ghost"; size?: "default" | "icon" }) {
  return <button className={`site-button button-${variant} ${size === "icon" ? "button-icon" : ""} ${className}`} {...props}>{children}</button>;
}

const NAV = [
  { href: "/#home", label: "Home", page: "home" },
  { href: "/#company", label: "Company", page: "company" },
  { href: "/why", label: "Why us", page: "why" },
  { href: "/pricing", label: "Pricing", page: "pricing" },
  { href: "/#news", label: "News", page: "news" },
  { href: "/contact", label: "Contact", page: "contact" },
];

/** Header shared by the marketing pages; `active` marks the current page in the nav. */
export function SiteHeader({ active }: { active: "home" | "why" | "pricing" | "contact" | "none" }) {
  const [mobile, setMobile] = useState(false);
  const { session, account } = useAccount();
  const cta = !session ? { href: "/get-started", label: "Get Started" }
    : account?.has_access ? { href: "/dashboard", label: "Dashboard" } : { href: "/choose-plan", label: "Choose a plan" };
  return <header className="site-header"><div className="nav-inner"><Link href="/" aria-label="Sheriff Sale Hunter home"><Brand/></Link><nav aria-label="Main navigation" className={mobile ? "main-nav is-open" : "main-nav"}>{NAV.map((item) => <Link key={item.href} href={item.href} className={item.page === active ? "active" : undefined} aria-current={item.page === active ? "page" : undefined} onClick={() => setMobile(false)}>{item.label}</Link>)}</nav><div className="nav-actions">{session && <Link href="/account" className="site-button button-ghost nav-cta">Account</Link>}<Link href={cta.href} className="site-button nav-cta">{cta.label}<ArrowUpRight/></Link><Button variant="ghost" size="icon" className="mobile-menu" aria-label={mobile ? "Close menu" : "Open menu"} onClick={() => setMobile(!mobile)}>{mobile ? <X/> : <Menu/>}</Button></div></div></header>;
}

export function SiteFooter() {
  return <footer className="site-footer"><div className="footer-top"><Link href="/"><Brand/></Link><span>Your Sheriff Sale Expert.</span><nav aria-label="Footer navigation"><Link href="/#company">Company</Link><Link href="/why">Why us</Link><Link href="/pricing">Pricing</Link><Link href="/#news">News</Link><Link href="/contact">Contact</Link></nav></div><div className="footer-bottom"><span>© {new Date().getFullYear()} Sheriff Sale Hunter. All rights reserved. <Link href="/terms">Terms</Link> · <Link href="/privacy">Privacy</Link></span><span>Intelligence for better-informed investments.<ArrowRight size={14}/></span></div></footer>;
}
