import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type ThemeMode = 'light' | 'dark';

interface ThemeStoreState {
  mode: ThemeMode;
  toggle: () => void;
  setMode: (m: ThemeMode) => void;
  apply: () => void;
}

function applyClass(mode: ThemeMode): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  if (mode === 'dark') root.classList.add('dark');
  else root.classList.remove('dark');
}

export const useThemeStore = create<ThemeStoreState>()(
  persist(
    (set, get) => ({
      mode: 'light',
      toggle: () => {
        const next: ThemeMode = get().mode === 'dark' ? 'light' : 'dark';
        applyClass(next);
        set({ mode: next });
      },
      setMode: (m) => {
        applyClass(m);
        set({ mode: m });
      },
      apply: () => {
        applyClass(get().mode);
      },
    }),
    {
      name: 'openrecruiting.theme.v1',
      version: 1,
      onRehydrateStorage: () => (state) => {
        if (state) applyClass(state.mode);
      },
    },
  ),
);
