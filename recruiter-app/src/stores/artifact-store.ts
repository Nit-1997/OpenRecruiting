import { create } from 'zustand';
import type { Artifact, ArtifactExpanded, ArtifactStatus, ArtifactType } from '@/types';

interface ArtifactStoreState {
  artifacts: Record<string, Artifact>;
  openArtifact: (args: {
    id: string;
    type: ArtifactType;
    title: string;
    initialData: unknown;
  }) => void;
  patchArtifact: (id: string, patch: Record<string, unknown>) => void;
  completeArtifact: (id: string) => void;
  setExpanded: (id: string, expanded: ArtifactExpanded) => void;
  expandArtifact: (id: string) => void;
  collapseArtifact: (id: string) => void;
  publishArtifact: (id: string) => void;
  saveDraft: (id: string) => void;
  archiveArtifact: (id: string) => void;
  removeArtifact: (id: string) => void;
  reset: () => void;
}

function setStatus(
  state: { artifacts: Record<string, Artifact> },
  id: string,
  status: ArtifactStatus,
) {
  const existing = state.artifacts[id];
  if (!existing) return state;
  return { artifacts: { ...state.artifacts, [id]: { ...existing, status } } };
}

export const useArtifactStore = create<ArtifactStoreState>((set) => ({
  artifacts: {},
  openArtifact: ({ id, type, title, initialData }) =>
    set((state) => {
      const base: Artifact = {
        id,
        type,
        title,
        data: initialData,
        isBuilding: true,
        expanded: 'default',
      };
      const artifact: Artifact = type === 'requisition' ? { ...base, status: 'draft' } : base;
      return { artifacts: { ...state.artifacts, [id]: artifact } };
    }),
  patchArtifact: (id, patch) =>
    set((state) => {
      const existing = state.artifacts[id];
      if (!existing) return state;
      const nextData =
        typeof existing.data === 'object' && existing.data !== null
          ? { ...(existing.data as Record<string, unknown>), ...patch }
          : patch;
      return {
        artifacts: { ...state.artifacts, [id]: { ...existing, data: nextData } },
      };
    }),
  completeArtifact: (id) =>
    set((state) => {
      const existing = state.artifacts[id];
      if (!existing) return state;
      return {
        artifacts: { ...state.artifacts, [id]: { ...existing, isBuilding: false } },
      };
    }),
  setExpanded: (id, expanded) =>
    set((state) => {
      const existing = state.artifacts[id];
      if (!existing) return state;
      return { artifacts: { ...state.artifacts, [id]: { ...existing, expanded } } };
    }),
  expandArtifact: (id) =>
    set((state) => {
      const existing = state.artifacts[id];
      if (!existing) return state;
      return {
        artifacts: { ...state.artifacts, [id]: { ...existing, expanded: 'expanded' } },
      };
    }),
  collapseArtifact: (id) =>
    set((state) => {
      const existing = state.artifacts[id];
      if (!existing) return state;
      return {
        artifacts: { ...state.artifacts, [id]: { ...existing, expanded: 'default' } },
      };
    }),
  publishArtifact: (id) => set((state) => setStatus(state, id, 'active')),
  saveDraft: (id) => set((state) => setStatus(state, id, 'draft')),
  archiveArtifact: (id) => set((state) => setStatus(state, id, 'archived')),
  removeArtifact: (id) =>
    set((state) => {
      const { [id]: _removed, ...rest } = state.artifacts;
      return { artifacts: rest };
    }),
  reset: () => set({ artifacts: {} }),
}));
