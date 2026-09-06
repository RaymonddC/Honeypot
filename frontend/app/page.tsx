import { redirect } from "next/navigation";

// Login is the front door — the root redirects straight to it. (Signed-in users
// hitting /login are bounced on to /home by the AppGate.)
export default function Root() {
  redirect("/login");
}
