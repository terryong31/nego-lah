<script setup lang="ts">
import type { AccordionItem } from '@nuxt/ui'

const { t } = useI18n()

const INCLUDED = ['listing', 'agent', 'payments', 'console'] as const

const faqItems = computed<AccordionItem[]>(() => [
  {
    label: t('home.deploy.faq.q1.label'),
    content: t('home.deploy.faq.q1.content')
  },
  {
    label: t('home.deploy.faq.q2.label'),
    content: t('home.deploy.faq.q2.content')
  },
  {
    label: t('home.deploy.faq.q3.label'),
    content: t('home.deploy.faq.q3.content')
  },
  {
    label: t('home.deploy.faq.q4.label'),
    content: t('home.deploy.faq.q4.content')
  },
  {
    label: t('home.deploy.faq.q5.label'),
    content: t('home.deploy.faq.q5.content')
  }
])
</script>

<template>
  <USection
    id="deploy"
    :ui="{
      root: 'relative left-1/2 -translate-x-1/2 w-screen scroll-mt-20 overflow-hidden bg-white dark:bg-zinc-950 text-default border-t border-default/40',
      container: 'relative max-w-(--ui-container) mx-auto px-4 sm:px-6 lg:px-8 py-16 sm:py-24'
    }"
  >
    <!-- Blueprint grid background & ambient blurs strictly contained -->
    <template #top>
      <div
        aria-hidden="true"
        class="absolute inset-0 overflow-hidden pointer-events-none"
      >
        <div
          class="absolute inset-0 opacity-[0.04] dark:opacity-[0.06] bg-[linear-gradient(to_right,black_1px,transparent_1px),linear-gradient(to_bottom,black_1px,transparent_1px)] dark:bg-[linear-gradient(to_right,white_1px,transparent_1px),linear-gradient(to_bottom,white_1px,transparent_1px)] bg-[size:48px_48px]"
        />
        <div
          class="absolute -top-32 right-0 size-96 rounded-full bg-primary/10 dark:bg-primary/20 blur-3xl"
        />
        <div
          class="absolute -bottom-40 left-0 size-80 rounded-full bg-sky-500/5 dark:bg-sky-500/10 blur-3xl"
        />
      </div>
    </template>

    <div class="grid lg:grid-cols-2 gap-12 lg:gap-16 items-start">
      <!-- Left: Pitch and Included Features -->
      <div class="space-y-6">
        <h2 class="text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight leading-[1.1] text-highlighted text-balance">
          {{ $t('home.deploy.title') }}
        </h2>

        <p class="text-base sm:text-lg text-muted leading-relaxed text-pretty">
          {{ $t('home.deploy.desc') }}
        </p>

        <ul class="space-y-3.5 pt-2">
          <li
            v-for="item in INCLUDED"
            :key="item"
            class="flex items-start gap-3 text-sm sm:text-base text-toned"
          >
            <UIcon
              name="i-lucide-check-circle-2"
              class="size-5 shrink-0 mt-0.5 text-primary"
            />
            <span>{{ $t(`home.deploy.included.${item}`) }}</span>
          </li>
        </ul>

        <div class="pt-2 flex justify-center lg:justify-start">
          <UButton
            to="mailto:contact@negolah.my?subject=Deploying%20Nego-lah%20at%20our%20company"
            size="xl"
            :label="$t('home.deploy.email')"
            icon="i-lucide-mail"
            class="font-bold shadow-lg hover:shadow-primary/30 transition-all duration-300 hover:scale-[1.02] active:scale-[0.98]"
          />
        </div>
      </div>

      <!-- Right: FAQ Accordion -->
      <div class="space-y-4">
        <h3 class="text-xl sm:text-2xl font-bold text-highlighted tracking-tight flex items-center gap-2 mb-6">
          <UIcon
            name="i-lucide-help-circle"
            class="size-5"
          />
          <span>{{ $t('home.deploy.faqTitle') }}</span>
        </h3>

        <UAccordion
          type="single"
          collapsible
          :default-value="['0']"
          :items="faqItems"
          :ui="{
            root: 'space-y-1',
            trigger: 'font-bold text-highlighted hover:text-primary transition-colors text-left text-sm sm:text-base cursor-pointer',
            body: 'pb-4 leading-relaxed'
          }"
        />
      </div>
    </div>
  </USection>
</template>
