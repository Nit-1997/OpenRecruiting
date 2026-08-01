import { IntakeCanvas } from '@/components/sub-agents/intake/canvas';

// Next.js 16 dynamic route — params is a Promise.
export default async function IntakeSessionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <div id="intake-session-page" className="p-6">
      <IntakeCanvas id="intake-session-page-canvas" sessionId={id} />
    </div>
  );
}
