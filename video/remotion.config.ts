import { Config } from '@remotion/cli/config'

// Flat colour and hard edges: PNG frames keep them crisp before H.264 encodes.
Config.setVideoImageFormat('png')
Config.setOverwriteOutput(true)
