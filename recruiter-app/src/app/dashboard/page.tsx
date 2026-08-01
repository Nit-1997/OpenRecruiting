import { redirect } from 'next/navigation';

// landing's post-login flow redirects to `${APP_URL}/dashboard` (a v1
// convention). app-v2's authenticated home is `/` (the shell). Alias /dashboard
// → / so landing's redirect lands correctly without changing landing's logic.
export default function DashboardAlias() {
  redirect('/');
}
