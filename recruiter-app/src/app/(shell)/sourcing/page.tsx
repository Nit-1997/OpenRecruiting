import { redirect } from 'next/navigation';

// Sourcing is temporarily disabled — the agent flow ships later.
// Code under /sub-agents/sourcing is intact; this route just bounces to home.
export default function SourcingPage() {
  redirect('/');
}
