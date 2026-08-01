import type { RailViewId } from './rail-view';
import type { SubAgentId } from './sub-agent';

export type ShellMode = 'home' | 'agentic' | 'qna';
export type ComposerMode = 'agentic' | 'qna' | 'voice';

export interface RailDetail {
  viewId: RailViewId;
  detailId: string;
}

export interface ShellState {
  activeTabId: SubAgentId | null;
  activeRailId: RailViewId | null;
  railDetail: RailDetail | null;
  stashed: SubAgentId | null;
}
