// @ts-check
import withNuxt from './.nuxt/eslint.config.mjs'

export default withNuxt(
  {
    // Both legal pages render a build-time constant from app/utils/legal.ts.
    files: ['app/pages/privacy.vue', 'app/pages/terms.vue'],
    rules: {
      'vue/no-v-html': 'off'
    }
  }
)
