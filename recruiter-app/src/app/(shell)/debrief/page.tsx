import { SUB_AGENT_REGISTRY } from '@/components/sub-agents';

export default function DebriefPage() {
  const Canvas = SUB_AGENT_REGISTRY.debrief.Canvas;
  return <Canvas id="debrief-canvas" />;
}
