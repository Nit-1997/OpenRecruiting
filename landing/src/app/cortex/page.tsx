import { redirect } from "next/navigation";

/**
 * Cortex was a separate page. It is now the second half of the homepage — the
 * same story told once — so this redirects rather than 404s: the URL has been
 * shared, and the nav link existed for a while.
 */
export default function CortexPage() {
  redirect("/#cortex");
}
