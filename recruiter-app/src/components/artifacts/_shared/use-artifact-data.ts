'use client';

import { useArtifactStore } from '@/stores';
import type { Artifact, ArtifactType, TypedArtifact } from '@/types';
import { asTypedArtifact } from '@/types';

type TypedArtifactFor<T extends ArtifactType> = Extract<TypedArtifact, { type: T }>;

/**
 * Reads an artifact from the store and returns it narrowed to its discriminated
 * union member for `type`. This replaces the blind `artifact.data as
 * XArtifactData` cast that lived in every artifact component: the discriminant
 * ties `type` to `data`, so `.data` (and `.isBuilding`, `.id`, ...) are
 * statically typed with no per-component cast.
 *
 * Returns `undefined` while the artifact has not been registered yet (the
 * expected pre-load state). Data is patched incrementally by the store, so the
 * narrowed value may still be partial — callers guard for required fields
 * exactly as they did before.
 */
export function useTypedArtifact<T extends ArtifactType>(
  artifactId: string,
  _type: T,
): TypedArtifactFor<T> | undefined {
  const artifact = useArtifactStore((s) => s.artifacts[artifactId]) as Artifact | undefined;
  if (!artifact) return undefined;
  return asTypedArtifact(artifact) as TypedArtifactFor<T>;
}
