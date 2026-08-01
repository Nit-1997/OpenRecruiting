import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { REQS, type RoleFixture } from '@/fixtures/roles';

interface RoleStoreState {
  roles: RoleFixture[];
  addRole: (role: RoleFixture) => void;
  updateRole: (id: string, patch: Partial<RoleFixture>) => void;
  removeRole: (id: string) => void;
  reset: () => void;
}

export const useRoleStore = create<RoleStoreState>()(
  persist(
    (set) => ({
      roles: [...REQS],
      addRole: (role) =>
        set((state) => ({
          roles: state.roles.some((r) => r.id === role.id)
            ? state.roles.map((r) => (r.id === role.id ? role : r))
            : [role, ...state.roles],
        })),
      updateRole: (id, patch) =>
        set((state) => ({
          roles: state.roles.map((r) => (r.id === id ? { ...r, ...patch } : r)),
        })),
      removeRole: (id) =>
        set((state) => ({
          roles: state.roles.filter((r) => r.id !== id),
        })),
      reset: () => set({ roles: [...REQS] }),
    }),
    { name: 'openrecruiting.roles.v1', version: 1 },
  ),
);
