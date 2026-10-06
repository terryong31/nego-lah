import { AbsoluteFill, useCurrentFrame } from 'remotion'
import { fall, pop, progress, shake } from '../motion'
import { Arch, Burst, Dot, Pill, Squiggle, Zigzag } from '../shapes'
import { C, DISPLAY, FLOAT, SLAM, STROKE, UI, hardShadow } from '../theme'
import { DEAL, NEGO } from '../timeline'
import { Check, PriceTag } from '../ui/parts'

const FINAL = NEGO.messages.reduce((p, m) => ('price' in m ? m.price : p), NEGO.startPrice as number)

/** Confetti made of the hero's shapes, thrown out from the stamp. */
const CONFETTI = Array.from({ length: 14 }, (_, i) => {
  const angle = (i / 14) * Math.PI * 2 + (i % 3) * 0.2
  const speed = 26 + (i % 4) * 7
  const kinds = [Burst, Dot, Pill, Zigzag, Arch, Squiggle] as const
  const colors = [C.yellow, C.red, C.pink, C.purple, C.orange, C.cyan]
  return { angle, speed, Shape: kinds[i % kinds.length]!, color: colors[(i * 5) % colors.length]!, size: 60 + (i % 3) * 26 }
})

/** The tag gets stamped, the money moves. */
export const Deal = () => {
  const frame = useCurrentFrame()
  const tag = pop(frame, DEAL.tag, FLOAT)
  const stamp = pop(frame, DEAL.stamp, SLAM)
  const hit = shake(frame, DEAL.stamp + 3)
  const pay = pop(frame, DEAL.pay)
  const fill = progress(frame, DEAL.pay + 4, DEAL.paid)
  const paid = pop(frame, DEAL.paid, SLAM)

  return (
    <AbsoluteFill style={{ background: C.green, overflow: 'hidden', transform: `translate(${hit.x}px, ${hit.y}px)` }}>
      {CONFETTI.map(({ angle, speed, Shape, color, size }, i) => {
        const t = Math.max(0, frame - DEAL.stamp - 2)
        if (t === 0) return null
        const x = 1330 + Math.cos(angle) * speed * t
        const y = 470 + Math.sin(angle) * speed * t + fall(frame, DEAL.stamp + 2, 1.4)
        return (
          <Shape
            key={i}
            size={size}
            color={color}
            style={{ left: x - size / 2, top: y - size / 2, transform: `rotate(${t * (i % 2 ? 9 : -9)}deg)` }}
          />
        )
      })}

      <PriceTag
        price={FINAL}
        size={2.2}
        color={C.yellow}
        style={{ left: 470, top: 190, transform: `rotate(-5deg) scale(${tag})` }}
      />

      {/* The rubber stamp. */}
      <div
        style={{
          position: 'absolute',
          left: 1080,
          top: 360,
          padding: '6px 10px',
          border: `${STROKE + 4}px solid ${C.red}`,
          borderRadius: 26,
          transform: `rotate(-14deg) scale(${frame < DEAL.stamp ? 0 : 3.2 - 2.2 * stamp})`,
          background: C.paper
        }}
      >
        <div
          style={{
            padding: '4px 40px',
            border: `${STROKE}px solid ${C.red}`,
            borderRadius: 18,
            fontFamily: DISPLAY,
            fontSize: 150,
            lineHeight: 1,
            color: C.red,
            letterSpacing: '0.02em'
          }}
        >
          DEAL
        </div>
      </div>

      {/* Checkout: the pill fills, then it is paid. */}
      <div
        style={{
          position: 'absolute',
          left: 560,
          top: 760,
          width: 800,
          height: 128,
          borderRadius: 999,
          border: `${STROKE}px solid ${C.ink}`,
          background: C.paper,
          boxShadow: hardShadow(12, C.pink),
          overflow: 'hidden',
          transform: `scale(${pay})`
        }}
      >
        <div style={{ position: 'absolute', inset: 0, width: `${fill * 100}%`, background: paid > 0.01 ? C.ink : C.yellow }} />
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 22,
            fontFamily: UI,
            fontWeight: 800,
            fontSize: 52,
            color: paid > 0.01 ? C.paper : C.ink
          }}
        >
          {paid > 0.01
            ? (
                <>
                  <div style={{ transform: `scale(${paid})`, display: 'flex' }}>
                    <Check size={64} color={C.green} progress={paid} />
                  </div>
                  Paid · RM{FINAL}
                </>
              )
            : `Paying RM${FINAL}…`}
        </div>
      </div>
    </AbsoluteFill>
  )
}
