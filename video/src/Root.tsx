import { Composition } from 'remotion'
import { Intro } from './Intro'
import { FPS, HEIGHT, WIDTH } from './theme'
import { DURATION } from './timeline'

export const RemotionRoot = () => (
  <Composition
    id="NegoLahIntro"
    component={Intro}
    durationInFrames={DURATION}
    fps={FPS}
    width={WIDTH}
    height={HEIGHT}
  />
)
