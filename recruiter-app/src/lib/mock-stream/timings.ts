export const STAGE_START_DELAY_MS = 220;
export const TOKEN_DELAY_MS = 16;
export const SUB_REVEAL_DELAY_MS = 180;
export const UX_REVEAL_DELAY_MS = 220;
export const ARTIFACT_TICK_DELAY_MS = 120;
export const STAGE_END_DELAY_MS = 160;

export function delayForEvent(evType: string): number {
  switch (evType) {
    case 'stage_start':
      return STAGE_START_DELAY_MS;
    case 'prose_token':
      return TOKEN_DELAY_MS;
    case 'sub_reveal':
      return SUB_REVEAL_DELAY_MS;
    case 'ux_reveal':
      return UX_REVEAL_DELAY_MS;
    case 'artifact_start':
      return ARTIFACT_TICK_DELAY_MS;
    case 'artifact_patch':
      return ARTIFACT_TICK_DELAY_MS;
    case 'artifact_complete':
      return 100;
    case 'stage_end':
      return STAGE_END_DELAY_MS;
    default:
      return 100;
  }
}
