import type { Metadata } from "next";
import { LoginScreen } from "./login-screen";

// Stays a server component purely to export `metadata`. All the copy lives in
// LoginScreen, which must be a client component to reach the locale — see the
// note at the top of login-screen.tsx.
export const metadata: Metadata = {
  title: "Sign in — ITTU",
};

export default function LoginPage() {
  return <LoginScreen />;
}
