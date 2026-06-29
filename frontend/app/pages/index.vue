<script setup lang="ts">
interface Item {
  item_id: string
  name: string
  description: string
  condition: string
  images: string
  price?: number
  min_price?: number
  status?: string
}

const { call } = useApi()

const { data: featured, pending } = useAsyncData(
  'featured-items',
  () => call<Item[]>('/items/featured'),
  { default: () => [] }
)

// --- Animated hero conversation ("chat -> sale") ---
interface Msg {
  id: string
  role: 'user' | 'assistant'
  side: 'left' | 'right'
  variant: 'soft' | 'solid'
  color: 'neutral' | 'primary'
  avatar?: { icon: string, size?: 'sm' }
  text: string
}

const conversation: Msg[] = [
  { id: 'm1', role: 'assistant', side: 'left', variant: 'soft', color: 'neutral', avatar: { icon: 'i-lucide-sparkles', size: 'sm' }, text: `That's Terry's Fender Strat — barely played. Asking RM320. 🎸` },
  { id: 'm2', role: 'user', side: 'right', variant: 'solid', color: 'primary', text: `Love it. Would you take RM240?` },
  { id: 'm3', role: 'assistant', side: 'left', variant: 'soft', color: 'neutral', avatar: { icon: 'i-lucide-sparkles', size: 'sm' }, text: `Cheeky 😄 I can do RM280 — fair for both of us.` },
  { id: 'm4', role: 'user', side: 'right', variant: 'solid', color: 'primary', text: `Deal! 🤝` },
  { id: 'm5', role: 'assistant', side: 'left', variant: 'soft', color: 'neutral', avatar: { icon: 'i-lucide-sparkles', size: 'sm' }, text: `Sold! I'll pack it up today. 📦` }
]

const visible = ref<Msg[]>([])
const typing = ref<Msg | null>(null)
const inputText = ref('')

let stopped = false
const timers: ReturnType<typeof setTimeout>[] = []
const wait = (ms: number) => new Promise<void>((resolve) => {
  timers.push(setTimeout(resolve, ms))
})

// Type a string into the fake input, character by character.
async function typeInto(text: string) {
  inputText.value = ''
  for (const ch of text) {
    inputText.value += ch
    await wait(40)
    if (stopped) return
  }
}

async function play() {
  await wait(700)
  for (const msg of conversation) {
    if (msg.role === 'user') {
      // The buyer "types" into the input, then sends it.
      await typeInto(msg.text)
      if (stopped) return
      await wait(450)
      if (stopped) return
      inputText.value = ''
      visible.value = [...visible.value, msg]
      await wait(900)
    } else {
      // The AI shows a typing indicator, then replies.
      typing.value = msg
      await wait(1100)
      if (stopped) return
      typing.value = null
      visible.value = [...visible.value, msg]
      await wait(1200)
    }
    if (stopped) return
  }
}

onMounted(() => {
  play()
})
onBeforeUnmount(() => {
  stopped = true
  timers.forEach(clearTimeout)
})
</script>

<template>
  <div>
    <!-- Hero Banner Section -->
    <div class="relative left-1/2 -translate-x-1/2 w-screen -mt-6 min-h-[580px] flex items-center bg-gradient-to-br from-primary/5 via-transparent to-primary/5">
      <div class="w-full max-w-(--ui-container) mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div class="grid lg:grid-cols-2 gap-10 lg:gap-16 items-center">
          <!-- Left: personal intro -->
          <div class="flex flex-col items-start gap-6 max-w-xl">
            <h1 class="text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight text-highlighted leading-[1.05]">
              Hi, I'm <span class="text-primary">Terry</span>.<br>
              I'm selling stuff,<br>
              Name your price.
            </h1>

            <p class="text-base sm:text-lg text-muted leading-relaxed">
              You can find mostly tech, musical instruments and household bits.
              See something you like? Haggle the price with my AI.<br>
              <span class="text-xs">P/S: You may get good deal if you can break it 😏</span>
            </p>

            <div class="flex flex-wrap items-center gap-3">
              <UButton
                to="/items"
                size="xl"
                label="Browse my stuff"
                trailing-icon="i-lucide-arrow-right"
              />
            </div>
          </div>

          <!-- Right: chat -> sale conversation -->
          <UCard
            class="w-full max-w-md lg:ml-auto shadow-xl"
            :ui="{ header: 'flex items-center gap-3', body: 'space-y-1' }"
          >
            <TransitionGroup
              tag="div"
              name="msg"
              class="relative space-y-1"
            >
              <UChatMessage
                v-for="m in visible"
                :id="m.id"
                :key="m.id"
                :role="m.role"
                :side="m.side"
                :variant="m.variant"
                :color="m.color"
                compact
                :avatar="m.avatar"
                :parts="[{ type: 'text', text: m.text }]"
                :ui="{ content: 'text-sm flex items-center px-3 py-2' }"
              />

              <!-- Typing indicator -->
              <UChatMessage
                v-if="typing"
                id="typing"
                key="typing"
                :role="typing.role"
                :side="typing.side"
                :variant="typing.variant"
                :color="typing.color"
                compact
                :avatar="typing.avatar"
                :parts="[]"
              >
                <template #content>
                  <span class="inline-flex items-center gap-1 py-0.5">
                    <span class="size-1.5 rounded-full bg-current animate-bounce [animation-delay:-0.3s]" />
                    <span class="size-1.5 rounded-full bg-current animate-bounce [animation-delay:-0.15s]" />
                    <span class="size-1.5 rounded-full bg-current animate-bounce" />
                  </span>
                </template>
              </UChatMessage>
            </TransitionGroup>

            <UInput
              v-model="inputText"
              class="w-full mt-2 pointer-events-none select-none"
              placeholder="Enter your message..."
              readonly
              tabindex="-1"
              trailing-icon="i-lucide-send"
            />
          </UCard>
        </div>
      </div>
    </div>

    <USeparator
      label="Featured Listings"
      position="start"
      :ui="{
        label: 'text-md'
      }"
      class="my-4"
    />

    <!-- Featured Section -->
    <div class="space-y-6">
      <!-- Item Grid list -->
      <ItemGrid
        :items="featured"
        :loading="pending"
      />
    </div>
  </div>
</template>

<style scoped>
.msg-enter-active {
  transition: opacity 0.35s ease, transform 0.35s ease;
}
.msg-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.msg-leave-active {
  transition: opacity 0.2s ease;
  position: absolute;
}
.msg-leave-to {
  opacity: 0;
}
.msg-move {
  transition: transform 0.3s ease;
}
</style>
