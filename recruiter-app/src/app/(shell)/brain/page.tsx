import { redirect } from 'next/navigation';
import { SUB_AGENT_REGISTRY } from '@/components/sub-agents';
import { isSubAgentLocked } from '@/lib/launch-flags';

export default function BrainPage() {
  // Coming soon pre-launch — block direct-URL access too (restore via launch-flags).
  if (isSubAgentLocked('brain')) redirect('/');
  const Canvas = SUB_AGENT_REGISTRY.brain.Canvas;
  return <Canvas id="brain-canvas" />;
}
