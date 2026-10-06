/**
 * The site's Memphis palette. Kept apart from `theme.ts` so the timeline (and
 * the render scripts that read it) never load fonts.
 */
export const C = {
  ink: '#16161D',
  paper: '#FFFFFF',
  orange: '#FB923C',
  red: '#F43F5E',
  yellow: '#FBBF24',
  purple: '#A855F7',
  cyan: '#06B6D4',
  pink: '#EC4899',
  green: '#00DC82',
  greenDeep: '#00A155'
} as const
