import type { ComponentType } from 'react'
import { AbsoluteFill, Sequence } from 'remotion'
import { Deal } from './scenes/Deal'
import { End } from './scenes/End'
import { Hook } from './scenes/Hook'
import { List } from './scenes/List'
import { Nego } from './scenes/Nego'
import { Ship } from './scenes/Ship'
import { Soundtrack } from './Soundtrack'
import { SCENES, WIPE, type SceneId } from './timeline'
import { ShapeWipe } from './ui/ShapeWipe'

const SCENE: Record<SceneId, ComponentType> = {
  hook: Hook,
  list: List,
  nego: Nego,
  deal: Deal,
  ship: Ship,
  end: End
}

/** The homepage intro (SPEC-100): six scenes, each cut under a shape wipe. */
export const Intro = () => (
  <AbsoluteFill>
    {SCENES.map(({ id, from, duration }) => {
      const Scene = SCENE[id]
      return (
        <Sequence key={id} name={id} from={from} durationInFrames={duration}>
          <Scene />
        </Sequence>
      )
    })}
    {/* Each wipe brings in the NEXT scene's colour and ends on the cut. */}
    {SCENES.slice(1).map(({ id, from, bg, wipe }) => (
      <Sequence key={`wipe-${id}`} name={`wipe → ${id}`} from={from - WIPE} durationInFrames={WIPE}>
        <ShapeWipe shape={wipe} color={bg} duration={WIPE} />
      </Sequence>
    ))}
    <Soundtrack />
  </AbsoluteFill>
)
