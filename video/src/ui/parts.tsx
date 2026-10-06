import type { CSSProperties, ReactNode } from 'react'
import { C, DISPLAY, STROKE, UI, hardShadow } from '../theme'

/**
 * The product's screens, rebuilt as vector parts. Proportions follow the
 * real app; the outlines and offset shadows are the film's own.
 */

/** A white panel with an ink outline and a solid offset shadow. */
export const Panel = ({ children, style, shadow = C.ink, radius = 28 }: {
  children?: ReactNode
  style?: CSSProperties
  shadow?: string
  radius?: number
}) => (
  <div
    style={{
      position: 'absolute',
      background: C.paper,
      border: `${STROKE}px solid ${C.ink}`,
      borderRadius: radius,
      boxShadow: hardShadow(14, shadow),
      ...style
    }}
  >
    {children}
  </div>
)

/** The film camera that is being sold, made of flat shapes. */
export const Camera = ({ width }: { width: number }) => (
  <svg viewBox="0 0 220 150" style={{ width, height: (width * 150) / 220, overflow: 'visible' }}>
    <rect x={30} y={18} width={46} height={22} rx={6} fill={C.ink} />
    <rect x={10} y={34} width={200} height={108} rx={18} fill={C.ink} />
    <rect x={10} y={62} width={200} height={50} fill={C.orange} />
    <circle cx={118} cy={88} r={46} fill={C.paper} stroke={C.ink} strokeWidth={10} />
    <circle cx={118} cy={88} r={26} fill={C.cyan} stroke={C.ink} strokeWidth={8} />
    <circle cx={108} cy={78} r={7} fill={C.paper} />
    <rect x={168} y={44} width={28} height={14} rx={4} fill={C.yellow} />
    <circle cx={34} cy={50} r={6} fill={C.red} />
  </svg>
)

/** A swing tag with an eyelet, rotated a little. */
export const PriceTag = ({ price, size = 1, color = C.pink, style, children }: {
  price: number | string
  size?: number
  color?: string
  style?: CSSProperties
  children?: ReactNode
}) => (
  <div
    style={{
      position: 'absolute',
      display: 'flex',
      alignItems: 'center',
      gap: 18 * size,
      padding: `${18 * size}px ${34 * size}px ${18 * size}px ${26 * size}px`,
      background: color,
      border: `${STROKE}px solid ${C.ink}`,
      borderRadius: `${20 * size}px ${60 * size}px ${60 * size}px ${20 * size}px`,
      boxShadow: hardShadow(10 * size),
      fontFamily: DISPLAY,
      fontSize: 72 * size,
      lineHeight: 1,
      color: C.ink,
      whiteSpace: 'nowrap',
      ...style
    }}
  >
    <div
      style={{
        width: 22 * size,
        height: 22 * size,
        borderRadius: '50%',
        background: C.paper,
        border: `${STROKE}px solid ${C.ink}`
      }}
    />
    <span style={{ fontSize: 34 * size, marginRight: -6 * size }}>RM</span>
    <span>{price}</span>
    {children}
  </div>
)

/** An app avatar: a coloured disc with a letter or a bot face. */
export const Avatar = ({ kind, size = 64 }: { kind: 'buyer' | 'agent', size?: number }) => (
  <div
    style={{
      width: size,
      height: size,
      flex: 'none',
      borderRadius: '50%',
      border: `${STROKE - 1}px solid ${C.ink}`,
      background: kind === 'buyer' ? C.pink : C.yellow,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: UI,
      fontWeight: 800,
      fontSize: size * 0.42,
      color: C.ink
    }}
  >
    {kind === 'buyer'
      ? 'B'
      : (
          <svg viewBox="0 0 30 30" style={{ width: size * 0.6, height: size * 0.6 }}>
            <rect x={4} y={8} width={22} height={17} rx={5} fill={C.ink} />
            <circle cx={11} cy={16} r={2.6} fill={C.green} />
            <circle cx={19} cy={16} r={2.6} fill={C.green} />
            <rect x={14} y={2} width={2.4} height={6} fill={C.ink} />
          </svg>
        )}
  </div>
)

/** A check mark, drawn by `progress` (0–1). */
export const Check = ({ size, progress = 1, color = C.ink }: { size: number, progress?: number, color?: string }) => (
  <svg viewBox="0 0 24 24" fill="none" style={{ width: size, height: size }}>
    <path
      d="M4 12.5 L10 18 L20 6"
      stroke={color}
      strokeWidth={3.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      pathLength={1}
      strokeDasharray={1}
      strokeDashoffset={1 - progress}
    />
  </svg>
)

/** The Nego-Lah mark: the favicon's chat-tag, flat (no gradient). */
export const Mark = ({ size }: { size: number }) => (
  <svg viewBox="0 0 40 40" style={{ width: size, height: size, overflow: 'visible' }}>
    <path
      d="M6 14C6 8.477 10.477 4 16 4h10c5.523 0 10 4.477 10 10v10c0 5.523-4.477 10-10 10H17l-7 4v-4.6C7.5 31.8 6 28.5 6 24V14z"
      fill={C.green}
      stroke={C.ink}
      strokeWidth={1.6}
      strokeLinejoin="round"
    />
    <circle cx={13} cy={11} r={2} fill={C.paper} stroke={C.ink} strokeWidth={0.9} />
    <path d="M16 26V15l8 10V14" stroke={C.ink} strokeWidth={2.9} strokeLinecap="round" strokeLinejoin="round" fill="none" />
    <path d="M28 10l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z" fill={C.yellow} stroke={C.ink} strokeWidth={0.6} />
  </svg>
)
