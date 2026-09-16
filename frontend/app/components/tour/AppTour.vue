<script setup lang="ts">
/**
 * The onboarding tour's chrome (SPEC-069).
 *
 * `useOnboardingTour` owns where the tour is and what it is pointing at; this
 * component is the only thing that draws it, and it is mounted once in
 * `app.vue` so it survives the `default` -> `chat` layout switch mid-tour.
 *
 * `UPopover` is non-modal here on purpose. The tour points, it never acts, so
 * the page underneath has to stay clickable — the reader is meant to do the
 * clicking. That also rules out a full-screen mask; the anchor is marked with
 * `data-tour-active` instead, which is an attribute toggle on an element that
 * is already there and so cannot shift the layout it is highlighting.
 */
const tour = useOnboardingTour()
const { t } = useI18n()

const step = computed(() => tour.current.value)

const title = computed(() => (step.value ? t(`tour.steps.${step.value.id}.title`) : ''))
const body = computed(() => (step.value ? t(`tour.steps.${step.value.id}.body`) : ''))

const progress = computed(() =>
  t('tour.progress', { current: tour.index.value + 1, total: tour.total.value })
)

const isLast = computed(() => !tour.hasNext.value)

/**
 * Highlight whatever the popover is anchored to. A step that is centred by
 * design, or one still waiting for its anchor to mount, highlights nothing.
 */
let marked: Element | null = null

function unmark() {
  marked?.removeAttribute('data-tour-active')
  marked = null
}

watch(
  () => [tour.open.value, tour.reference.value] as const,
  ([open, reference]) => {
    unmark()
    if (!open) return
    if (reference instanceof Element) {
      reference.setAttribute('data-tour-active', '')
      marked = reference
    }
  },
  { immediate: true, flush: 'post' }
)

onBeforeUnmount(unmark)
</script>

<template>
  <UPopover
    :open="tour.open.value"
    :reference="tour.reference.value"
    :dismissible="false"
    :modal="false"
    :content="{
      side: step?.side ?? 'bottom',
      align: 'center',
      sideOffset: 12,
      onOpenAutoFocus: (event: Event) => event.preventDefault()
    }"
  >
    <template #content>
      <div class="w-[min(20rem,calc(100vw-2rem))] p-4 space-y-3">
        <div class="space-y-1.5">
          <div class="flex items-center justify-between gap-3">
            <p class="font-bold text-highlighted leading-snug">
              {{ title }}
            </p>
            <span class="text-xs text-muted tabular-nums shrink-0">
              {{ progress }}
            </span>
          </div>
          <p class="text-sm text-muted leading-relaxed text-pretty">
            {{ body }}
          </p>
        </div>

        <!--
          The checkout card only exists after a deal, so a first-time reader
          has nothing to point at. Draw one rather than describe it.
        -->
        <div
          v-if="step?.id === 'payCard'"
          class="rounded-xl bg-elevated/60 p-3 space-y-2"
        >
          <p class="text-lg font-extrabold tracking-tight text-highlighted tabular-nums">
            {{ $t('tour.payDemoLabel') }}
          </p>
          <div class="flex items-center gap-1.5 text-xs text-muted">
            <UIcon
              name="i-lucide-lock"
              class="size-3 shrink-0"
            />
            <span>{{ $t('tour.payDemoNote') }}</span>
          </div>
        </div>

        <div class="flex items-center justify-between gap-2 pt-1">
          <UButton
            data-testid="tour-skip"
            :label="$t('tour.skip')"
            color="neutral"
            variant="ghost"
            size="xs"
            @click="tour.skip()"
          />
          <div class="flex items-center gap-1.5">
            <UButton
              data-testid="tour-back"
              :label="$t('tour.back')"
              color="neutral"
              variant="ghost"
              size="xs"
              :disabled="!tour.hasPrev.value"
              @click="tour.prev()"
            />
            <UButton
              data-testid="tour-next"
              :label="isLast ? $t('tour.finish') : $t('tour.next')"
              color="primary"
              size="xs"
              @click="isLast ? tour.finish() : tour.next()"
            />
          </div>
        </div>
      </div>
    </template>
  </UPopover>
</template>

<style>
/*
 * Global, not scoped: the element being highlighted belongs to whichever page
 * is on screen, not to this component.
 */
[data-tour-active] {
  outline: 2px solid var(--ui-primary);
  outline-offset: 4px;
  border-radius: var(--ui-radius);
  transition: outline-color 150ms ease-out;
}
</style>
