import { AbsoluteFill, useCurrentFrame } from 'remotion'
import { pop } from '../motion'
import { Burst, Donut, Zigzag } from '../shapes'
import { C, FLOAT, SLAM, UI } from '../theme'
import { LIST, NEGO } from '../timeline'
import { Camera, Check, Panel, PriceTag } from '../ui/parts'
import { SlamText } from '../ui/SlamText'

/** The seller lists the thing once. The card assembles; the tag stamps on. */
export const List = () => {
  const frame = useCurrentFrame()
  const card = pop(frame, LIST.card, FLOAT)
  const photo = pop(frame, LIST.card + 6, SLAM)
  const tag = pop(frame, LIST.tag, SLAM)
  const listed = pop(frame, LIST.listed)
  const bob = Math.sin(frame / 9) * 8

  return (
    <AbsoluteFill style={{ background: C.yellow, overflow: 'hidden' }}>
      <Burst size={720} color={C.orange} style={{ left: 1040, top: 140, transform: `rotate(${frame * 0.6}deg) scale(${card})` }} />
      <Zigzag size={200} style={{ left: 120, top: 760, transform: `translateY(${bob}px)` }} />
      <Donut size={150} style={{ left: 840, top: 90, transform: `rotate(${frame}deg)` }} />

      <div style={{ position: 'absolute', left: 130, top: 290 }}>
        <SlamText text="List it" at={LIST.title} size={210} color={C.ink} shadow={C.paper} />
        <SlamText text="once." at={LIST.title + 7} size={210} color={C.paper} shadow={C.ink} style={{ marginTop: 6 }} />
      </div>

      {/* The listing card, as the storefront draws it. */}
      <Panel
        style={{
          left: 1060,
          top: 170,
          width: 640,
          height: 700,
          transform: `translateY(${(1 - card) * 900}px) rotate(${(1 - card) * 12 + 3}deg)`
        }}
      >
        <div
          style={{
            margin: 24,
            height: 420,
            borderRadius: 18,
            border: `6px solid ${C.ink}`,
            background: C.cyan,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            overflow: 'hidden'
          }}
        >
          <div style={{ transform: `scale(${photo}) rotate(${(1 - photo) * -20}deg)` }}>
            <Camera width={420} />
          </div>
        </div>
        <div style={{ padding: '6px 34px', fontFamily: UI, color: C.ink }}>
          <div style={{ fontSize: 52, fontWeight: 800, letterSpacing: '-0.02em' }}>Retro film camera</div>
          <div style={{ fontSize: 32, fontWeight: 500, marginTop: 10, opacity: 0.7 }}>Good condition · Petaling Jaya</div>
          <div
            style={{
              marginTop: 30,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 12,
              padding: '10px 24px 10px 16px',
              borderRadius: 999,
              border: `5px solid ${C.ink}`,
              background: C.green,
              fontSize: 30,
              fontWeight: 800,
              transform: `scale(${listed})`,
              transformOrigin: 'left center'
            }}
          >
            <Check size={34} progress={listed} />
            Listed
          </div>
        </div>
      </Panel>

      <PriceTag
        price={NEGO.startPrice}
        size={1.25}
        style={{
          left: 1440,
          top: 470,
          transform: `scale(${tag ? 2.6 - 1.6 * tag : 0}) rotate(${-8 + (1 - tag) * -30}deg)`,
          opacity: tag > 0.01 ? 1 : 0
        }}
      />
    </AbsoluteFill>
  )
}
