// Mirrors an in-progress intake requisition onto the roles dashboard via the
// services layer. Extracted out of `RequisitionArtifact` so the view stays
// presentational: this module owns the async orchestration (create-or-update
// the dashboard requisition, then mirror any screening-agent attachment).
//
// Behaviour is identical to the former in-component closure — it reads the
// latest intake requisition from `useRequisitionStore` for the cached mirror
// id, falls back to creating one, and swallows non-`not_found` service errors
// the same way.

import { requisitions as requisitionsService } from '@/services';
import { ServiceError } from '@/services/service-error';
import { useRequisitionStore } from '@/stores';
import type { Requisition } from '@/types';

export type MirrorTargetStatus = 'planned' | 'intake_pending';

export async function mirrorIntakeToDashboard(
  req: Requisition,
  targetStatus: MirrorTargetStatus,
): Promise<string | null> {
  // If we've already mirrored this intake req to the roles dashboard, reuse
  // that services-layer id. Otherwise create one now and stash it.
  const existing = useRequisitionStore.getState().requisitions[req.id];
  const existingMirrorId = existing?.dashboardRequisitionId ?? null;
  try {
    if (existingMirrorId) {
      await requisitionsService.setStatus(existingMirrorId, targetStatus).catch((err) => {
        if (err instanceof ServiceError && err.code !== 'not_found') throw err;
      });
      return existingMirrorId;
    }
    const created = await requisitionsService.create({
      role_title: req.roleTitle,
      role_location: req.roleLocation || 'Remote',
      department: 'Product',
      created_by: 'user_1',
      created_by_name: 'Nitin',
      experience_min_years: req.experienceMinYears ?? 3,
      experience_max_years: req.experienceMaxYears ?? null,
      job_description: req.intakeSummary ?? '',
      must_have_skills: Array.from(new Set(req.rounds.flatMap((r) => r.skills ?? []))),
      good_to_have_skills: [],
      round_template: 'staff_pm_4',
    });
    await requisitionsService.setStatus(created.id, targetStatus).catch(() => null);
    // Mirror any screening-agent attachment from the intake requisition onto
    // the dashboard's first screening round so the Plan tab shows it.
    const intakeScreening = req.rounds.find((r) => r.screeningAgentEnabled);
    if (intakeScreening?.screeningAgentQuestions?.length) {
      const domainScreening = created.rounds.find((r) => r.category === 'screening');
      if (domainScreening) {
        const mapped = intakeScreening.screeningAgentQuestions.map((q) => ({
          id: q.id,
          order: q.order,
          dimension: q.dimension,
          question: q.question,
          probe: q.probe,
          duration_minutes: q.durationMinutes,
          signal: q.signal,
        }));
        await requisitionsService
          .attachScreeningAgent(domainScreening.id, mapped)
          .catch(() => null);
      }
    }
    useRequisitionStore.getState().setDashboardRequisitionId?.(req.id, created.id);
    return created.id;
  } catch (err) {
    if (err instanceof ServiceError) {
      console.warn(`[intake] mirror-to-dashboard failed: ${err.code}: ${err.message}`);
    }
    return null;
  }
}
