import { AbsoluteFill, useCurrentFrame } from 'remotion'
import { easeInOut, pop, progress } from '../motion'
import { Arch, Burst, Donut } from '../shapes'
import { C, SLAM, STROKE, UI, hardShadow } from '../theme'
import { SHIP } from '../timeline'
import { Check, Mark } from '../ui/parts'
import { SlamText } from '../ui/SlamText'

const LEFT = 250
const RIGHT = 1670
const TRACK_Y = 660
const LABELS = ['Paid', 'Shipped', 'Delivered']

/** The order tracker, with the parcel riding it. */
export const Ship = () => {
  const frame = useCurrentFrame()
  const travel = easeInOut(progress(frame, SHIP.depart, SHIP.arrive))
  const x = LEFT + (RIGHT - LEFT) * travel
  const moving = frame > SHIP.depart && frame < SHIP.arrive
  const hop = moving ? Math.abs(Math.sin((frame - SHIP.depart) / 2.4)) * -46 : 0
  const tilt = moving ? Math.sin((frame - SHIP.depart) / 2.4) * 8 : 0
  const parcel = pop(frame, 4, SLAM)

  return (
    <AbsoluteFill style={{ background: C.cyan, overflow: 'hidden' }}>
      <Burst size={150} style={{ left: 1650, top: 90, transform: `rotate(${frame * 2}deg)` }} />
      <Arch size={140} style={{ left: 90, top: 880 }} />
      <Donut size={130} color={C.paper} style={{ left: 1500, top: 880, transform: `rotate(${-frame * 1.5}deg)` }} />

      <div style={{ position: 'absolute', left: 140, top: 100 }}>
        <SlamText text="Then it ships." at={SHIP.title} size={170} color={C.paper} shadow={C.ink} />
      </div>

      {/* The track: dashed ahead of the parcel, solid behind it. */}
      <svg style={{ position: 'absolute', inset: 0, width: 1920, height: 1080 }}>
        <line
          x1={LEFT}
          y1={TRACK_Y}
          x2={RIGHT}
          y2={TRACK_Y}
          stroke={C.ink}
          strokeWidth={10}
          strokeDasharray="28 22"
          strokeDashoffset={-frame * 3}
          strokeLinecap="round"
        />
        <line x1={LEFT} y1={TRACK_Y} x2={x} y2={TRACK_Y} stroke={C.ink} strokeWidth={22} strokeLinecap="round" />
      </svg>

      {SHIP.stops.map((stop, i) => {
        const reached = SHIP.depart + (SHIP.arrive - SHIP.depart) * stop
        const done = pop(frame, i === 0 ? 0 : reached, SLAM)
        return (
          <div
            key={stop}
            style={{
              position: 'absolute',
              left: LEFT + (RIGHT - LEFT) * stop - 60,
              top: TRACK_Y - 60,
              width: 120,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center'
            }}
          >
            <div
              style={{
                width: 120,
                height: 120,
                borderRadius: '50%',
                border: `${STROKE + 2}px solid ${C.ink}`,
                background: done > 0.5 ? C.green : C.paper,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transform: `scale(${0.8 + 0.2 * done})`
              }}
            >
              <Check size={70} progress={done} />
            </div>
            <div
              style={{
                marginTop: 30,
                fontFamily: UI,
                fontWeight: 800,
                fontSize: 44,
                color: C.ink,
                whiteSpace: 'nowrap'
              }}
            >
              {LABELS[i]}
            </div>
          </div>
        )
      })}

      {/* The parcel. */}
      <div
        style={{
          position: 'absolute',
          left: x - 110,
          top: TRACK_Y - 290 + hop,
          width: 220,
          height: 180,
          background: C.orange,
          border: `${STROKE + 2}px solid ${C.ink}`,
          borderRadius: 18,
          boxShadow: hardShadow(12),
          transform: `rotate(${tilt}deg) scale(${parcel})`
        }}
      >
        <div style={{ position: 'absolute', left: 92, top: -2, width: 24, height: 176, background: C.yellow, borderLeft: `5px solid ${C.ink}`, borderRight: `5px solid ${C.ink}` }} />
        <div style={{ position: 'absolute', left: 18, top: 92, transform: 'rotate(-10deg)' }}>
          <Mark size={62} />
        </div>
      </div>
    </AbsoluteFill>
  )
}
