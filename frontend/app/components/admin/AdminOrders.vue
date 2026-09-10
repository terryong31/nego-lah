<script setup lang="ts">
import { computed, h, reactive, ref, resolveComponent } from 'vue'
import type { DropdownMenuItem, TableColumn } from '@nuxt/ui'

const UButton = resolveComponent('UButton')

const { t } = useI18n()
const { call } = useAdminApi()
const toast = useToast()

interface Order {
  id: string
  item_name: string
  amount: number
  status: string
  buyer_name?: string
  buyer_email?: string
  recipient_name?: string
  address?: string
  phone?: string
  notes?: string
  created_at: string
  // SPEC-057 postage. All nullable: orders placed before it, and orders not yet
  // shipped, simply have none of these.
  courier?: string | null
  tracking_number?: string | null
  tracking_url?: string | null
  shipped_at?: string | null
  delivered_at?: string | null
}
interface OrdersResponse {
  orders: Order[]
  stats: { total_orders: number, total_sales: number }
}

const { data, pending, refresh } = useAsyncData<OrdersResponse>(
  'admin-orders',
  () => call<OrdersResponse>('/orders'),
  { default: () => ({ orders: [], stats: { total_orders: 0, total_sales: 0 } }) }
)

const orders = computed(() => data.value.orders)

const statusItems = computed(() => [
  { label: t('admin.ordersSection.statusPendingInfo'), value: 'pending_info' },
  { label: t('admin.ordersSection.statusConfirmed'), value: 'confirmed' },
  { label: t('admin.ordersSection.statusShipped'), value: 'shipped' },
  { label: t('admin.ordersSection.statusDelivered'), value: 'delivered' },
  { label: t('admin.ordersSection.statusCancelled'), value: 'cancelled' },
  { label: t('admin.ordersSection.statusRefunded'), value: 'refunded' }
])
const busy = ref<string | null>(null)

// Native Nuxt UI Expanded row tracking
const expanded = ref({})

// --- SPEC-057: postage ----------------------------------------------------
// Kept per order id rather than in a single "current" object, so expanding two
// rows and typing in both doesn't let one overwrite the other on submit.
interface ShipmentDraft {
  courier: string
  trackingNumber: string
  trackingUrl: string
  notify: boolean
}
const shipmentDrafts = reactive<Record<string, ShipmentDraft>>({})

// Mirrors domains/catalog/shipping.COURIER_CHOICES. The field stays free-text —
// the backend recognises these names plus the obvious misspellings, and records
// anything else as typed.
const COURIERS = [
  'J&T Express',
  'Pos Laju',
  'Ninja Van',
  'City-Link Express',
  'DHL eCommerce',
  'Flash Express',
  'GDEX',
  'Shopee Express'
]

function shipmentDraft(o: Order): ShipmentDraft {
  return (shipmentDrafts[o.id] ||= {
    courier: o.courier || '',
    trackingNumber: o.tracking_number || '',
    trackingUrl: o.tracking_url || '',
    // A first post tells the buyer. A correction does not, unless the seller
    // says so: the buyer has already been told once, and re-telling them should
    // be a decision rather than something a mistyped digit drags along.
    notify: !o.shipped_at
  })
}

// SPEC-064 — the postage form lives in a modal now. It used to be four fields
// inside an expanded row, so posting a parcel meant noticing there was a
// chevron, expanding, scrolling past the address, and filling in a form sharing
// a cramped grid column. Nothing on the collapsed row said an order still
// needed posting.
const shippingOrder = ref<Order | null>(null)
const shippingOpen = computed({
  get: () => shippingOrder.value !== null,
  set: (open: boolean) => {
    if (!open) shippingOrder.value = null
  }
})

function openShipment(o: Order) {
  shipmentDraft(o)
  shippingOrder.value = o
}

async function recordShipment(o: Order) {
  const draft = shipmentDraft(o)
  if (!draft.courier.trim() || !draft.trackingNumber.trim()) {
    toast.add({ title: t('admin.ordersSection.shipmentRequired'), color: 'warning' })
    return
  }

  busy.value = o.id
  try {
    const res = await call<{
      order: Order
      notified: { email: boolean, chat: boolean }
    }>(`/orders/${o.id}/shipment`, {
      method: 'PUT',
      body: {
        courier: draft.courier.trim(),
        tracking_number: draft.trackingNumber.trim(),
        tracking_url: draft.trackingUrl.trim() || undefined,
        notify: draft.notify
      }
    })

    Object.assign(o, {
      status: 'shipped',
      courier: res.order.courier,
      tracking_number: res.order.tracking_number,
      tracking_url: res.order.tracking_url,
      shipped_at: res.order.shipped_at
    })
    draft.courier = res.order.courier || draft.courier
    draft.trackingUrl = res.order.tracking_url || ''
    // It is recorded; there is nothing left in the form to lose. A failed write
    // deliberately leaves the modal open with the draft intact.
    shippingOrder.value = null

    // Say what actually happened. "Recorded" when the buyer was told, and a
    // distinct warning when the write landed but the notification didn't —
    // otherwise the seller assumes the buyer knows, and nobody chases it.
    const notified = res.notified?.email || res.notified?.chat
    if (!draft.notify) {
      toast.add({ title: t('admin.ordersSection.shipmentRecorded'), description: t('admin.ordersSection.shipmentRecordedQuiet'), color: 'success' })
    } else if (notified) {
      toast.add({ title: t('admin.ordersSection.shipmentRecorded'), description: t('admin.ordersSection.shipmentRecordedNotified'), color: 'success' })
    } else {
      toast.add({ title: t('admin.ordersSection.shipmentRecorded'), description: t('admin.ordersSection.shipmentPartial'), color: 'warning' })
    }
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: t('admin.ordersSection.shipmentFailed'), description: e.data?.detail || e.message, color: 'error' })
  } finally {
    busy.value = null
  }
}

function statusColor(s: string) {
  if (s === 'delivered') return 'success' as const
  if (s === 'shipped' || s === 'confirmed') return 'info' as const
  if (s === 'pending_info') return 'warning' as const
  if (s === 'refunded') return 'neutral' as const
  return 'error' as const
}

async function changeStatus(o: Order, status: string) {
  if (status === o.status) return
  busy.value = o.id
  try {
    await call(`/orders/${o.id}/status`, { method: 'PUT', body: { status } })
    o.status = status
    toast.add({ title: t('admin.ordersSection.markedSuccess', { status: status.replace('_', ' ') }), color: 'success' })
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: t('admin.ordersSection.updateFailed'), description: e.data?.detail || e.message, color: 'error' })
  } finally {
    busy.value = null
  }
}

async function remove(o: Order) {
  if (!confirm(t('admin.ordersSection.deleteConfirm', { name: o.item_name || 'Untitled' }))) return
  busy.value = o.id
  try {
    await call(`/orders/${o.id}`, { method: 'DELETE' })
    toast.add({ title: t('admin.ordersSection.deletedSuccess'), color: 'success' })
    await refresh()
  } catch (err) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({ title: t('admin.ordersSection.deleteFailed'), description: e.data?.detail || e.message, color: 'error' })
  } finally {
    busy.value = null
  }
}

function formatDate(d: string) {
  return d ? new Date(d).toLocaleDateString('en-MY', { year: 'numeric', month: 'short', day: 'numeric' }) : '-'
}

function hasShippingInfo(o: Order) {
  return o.recipient_name || o.address || o.phone
}

// SPEC-064 — the select restated the Status column and made the seller's most
// common act look like a dropdown choice. What replaces it is one contextual
// button for the thing this order actually needs, and a menu for the rest: the
// transitions still have to exist, they just don't deserve the widest column.
function shipLabel(o: Order): string | null {
  if (o.shipped_at || o.status === 'shipped' || o.status === 'delivered') {
    return t('admin.ordersSection.editShipment')
  }
  if (o.status === 'confirmed') {
    return t('admin.ordersSection.ship')
  }
  return null
}

function rowActions(o: Order): DropdownMenuItem[][] {
  const transitions = statusItems.value
    .filter(i => i.value !== o.status)
    .map(i => ({
      label: t('admin.ordersSection.markAs', { status: i.label }),
      onSelect: () => changeStatus(o, i.value)
    }))

  return [
    transitions,
    [{
      label: t('admin.ordersSection.delete'),
      icon: 'i-lucide-trash-2',
      color: 'error' as const,
      onSelect: () => remove(o)
    }]
  ]
}

// SPEC-065 — filtering goes through the table's own row model rather than a
// filter over `orders`, so sorting and row expansion keep working on the
// filtered set.
const globalFilter = ref('')
const table = useTemplateRef<{ tableApi?: { getFilteredRowModel: () => { rows: unknown[] } } }>('table')

// The count has to describe what is on screen: "42 order(s)" above three rows
// is simply false. Falls back to the source length until the table has mounted.
const visibleCount = computed(() => {
  void globalFilter.value
  void orders.value
  return table.value?.tableApi?.getFilteredRowModel().rows.length ?? orders.value.length
})

const columns = computed<TableColumn<Order>[]>(() => [
  {
    id: 'expand',
    cell: ({ row }) => h(UButton, {
      'color': 'neutral',
      'variant': 'ghost',
      'icon': 'i-lucide-chevron-right',
      'square': true,
      'aria-label': 'Expand',
      'ui': {
        leadingIcon: ['transition-transform', row.getIsExpanded() ? 'duration-200 rotate-90' : '']
      },
      'onClick': () => row.toggleExpanded()
    })
  },
  { accessorKey: 'item_name', header: t('admin.ordersSection.colOrder') },
  { accessorKey: 'buyer_name', header: t('admin.ordersSection.colBuyer') },
  { accessorKey: 'amount', header: t('admin.ordersSection.colAmount') },
  { accessorKey: 'status', header: t('admin.ordersSection.colStatus') },
  { accessorKey: 'created_at', header: t('admin.ordersSection.colDate') },
  { id: 'actions', header: '' }
])
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center gap-3">
      <UInput
        v-model="globalFilter"
        size="md"
        icon="i-lucide-search"
        class="flex-1 min-w-0 max-w-xs"
        :placeholder="$t('admin.ordersSection.searchPlaceholder')"
        :aria-label="$t('admin.ordersSection.searchPlaceholder')"
      />
      <p class="text-sm text-muted shrink-0">
        {{ $t('admin.ordersSection.count', { n: visibleCount }) }}
      </p>
      <UButton
        class="ms-auto shrink-0"
        size="md"
        variant="ghost"
        icon="i-lucide-refresh-cw"
        :label="$t('admin.ordersSection.refresh')"
        :loading="pending"
        @click="refresh()"
      />
    </div>

    <UTable
      ref="table"
      v-model:expanded="expanded"
      v-model:global-filter="globalFilter"
      :columns="columns"
      :data="orders"
      :loading="pending"
      :ui="{ td: 'py-2', tr: 'data-[expanded=true]:bg-elevated/50' }"
    >
      <template #empty>
        <UEmpty
          :icon="globalFilter ? 'i-lucide-search-x' : 'i-lucide-package'"
          :title="globalFilter ? $t('admin.ordersSection.noMatchTitle') : $t('admin.ordersSection.emptyTitle')"
          :description="globalFilter ? $t('admin.ordersSection.noMatchDesc') : $t('admin.ordersSection.emptyDesc')"
          variant="naked"
          class="py-6"
        />
      </template>

      <template #item_name-cell="{ row }">
        <p class="font-medium text-highlighted truncate max-w-50">
          {{ row.original.item_name || 'Untitled' }}
        </p>
      </template>

      <template #buyer_name-cell="{ row }">
        <div class="min-w-0">
          <p class="text-sm text-default truncate">
            {{ row.original.buyer_name || 'Unknown' }}
          </p>
          <p class="text-xs text-muted truncate">
            {{ row.original.buyer_email || '—' }}
          </p>
        </div>
      </template>

      <template #amount-cell="{ row }">
        <span class="font-semibold">RM {{ (row.original.amount || 0).toFixed(2) }}</span>
      </template>

      <template #status-cell="{ row }">
        <UBadge
          :color="statusColor(row.original.status)"
          variant="subtle"
          size="sm"
          class="capitalize"
        >
          {{ row.original.status?.replace('_', ' ') }}
        </UBadge>
      </template>

      <template #created_at-cell="{ row }">
        <span class="text-sm text-muted">{{ formatDate(row.original.created_at) }}</span>
      </template>

      <template #actions-cell="{ row }">
        <div class="flex items-center justify-end gap-1">
          <UButton
            v-if="shipLabel(row.original)"
            variant="link"
            size="sm"
            icon="i-lucide-truck"
            :label="shipLabel(row.original) || undefined"
            :loading="busy === row.original.id"
            @click="openShipment(row.original)"
          />
          <UDropdownMenu
            :items="rowActions(row.original)"
            :content="{ align: 'end' }"
          >
            <UButton
              :data-testid="`order-actions-${row.original.id}`"
              size="sm"
              variant="ghost"
              color="neutral"
              icon="i-lucide-ellipsis-vertical"
              :loading="busy === row.original.id"
              :aria-label="$t('admin.ordersSection.rowActions')"
            />
          </UDropdownMenu>
        </div>
      </template>

      <template #expanded="{ row }">
        <div class="grid gap-6 sm:grid-cols-2">
          <div>
            <p class="text-sm font-semibold text-highlighted mb-2">
              {{ $t('admin.ordersSection.shippingTitle') }}
            </p>
            <div class="flex flex-col text-sm text-default space-y-1">
              <div><span class="text-muted">{{ $t('admin.ordersSection.recipient') }}:</span> {{ row.original.recipient_name || '—' }}</div>
              <div><span class="text-muted">{{ $t('admin.ordersSection.address') }}:</span> <span class="whitespace-pre-line">{{ row.original.address || '—' }}</span></div>
              <div><span class="text-muted">{{ $t('admin.ordersSection.phone') }}:</span> {{ row.original.phone || '—' }}</div>
              <div v-if="row.original.notes">
                <span class="text-muted">{{ $t('admin.ordersSection.notes') }}:</span> {{ row.original.notes }}
              </div>
            </div>
            <p
              v-if="!hasShippingInfo(row.original)"
              class="text-sm text-muted italic mt-2"
            >
              {{ $t('admin.ordersSection.noShippingInfo') }}
            </p>
          </div>

          <!-- SPEC-064: a record, not an editor. The form moved to the modal
               the row's own Ship / Edit shipment button opens. -->
          <div>
            <div class="flex items-center justify-between mb-2 gap-2">
              <p class="text-sm font-semibold text-highlighted">
                {{ $t('admin.ordersSection.postageTitle') }}
              </p>
              <span
                v-if="row.original.shipped_at"
                class="text-xs text-muted"
              >
                {{ row.original.delivered_at
                  ? `${$t('admin.ordersSection.deliveredOn')} ${formatDate(row.original.delivered_at)}`
                  : `${$t('admin.ordersSection.shippedOn')} ${formatDate(row.original.shipped_at)}` }}
              </span>
            </div>

            <div
              v-if="row.original.shipped_at"
              class="flex flex-col text-sm text-default space-y-1"
            >
              <div>
                <span class="text-muted">{{ $t('admin.ordersSection.courier') }}:</span>
                {{ row.original.courier || '—' }}
              </div>
              <div>
                <span class="text-muted">{{ $t('admin.ordersSection.trackingNumber') }}:</span>
                {{ row.original.tracking_number || '—' }}
              </div>
              <div
                v-if="row.original.tracking_url"
                class="pt-1"
              >
                <UButton
                  size="xs"
                  variant="link"
                  class="p-0"
                  icon="i-lucide-external-link"
                  :to="row.original.tracking_url"
                  target="_blank"
                  rel="noopener noreferrer"
                  :label="$t('admin.ordersSection.trackParcel')"
                />
              </div>
            </div>
            <p
              v-else
              class="text-sm text-muted italic"
            >
              {{ $t('admin.ordersSection.notPostedYet') }}
            </p>
          </div>
        </div>
      </template>
    </UTable>

    <!-- SPEC-064. One submit records the tracking AND tells the buyer, because
         a seller who has to remember the second half eventually won't. -->
    <UModal
      v-model:open="shippingOpen"
      :title="shippingOrder?.shipped_at
        ? $t('admin.ordersSection.editShipment')
        : $t('admin.ordersSection.recordShipment')"
      :description="shippingOrder?.item_name || undefined"
    >
      <template #body>
        <div
          v-if="shippingOrder"
          class="space-y-3"
        >
          <UFormField :label="$t('admin.ordersSection.courier')">
            <UInputMenu
              v-model="shipmentDraft(shippingOrder).courier"
              :items="COURIERS"
              create-item
              :placeholder="$t('admin.ordersSection.courierPlaceholder')"
              class="w-full"
              @create="(v: string) => { if (shippingOrder) shipmentDraft(shippingOrder).courier = v }"
            />
          </UFormField>

          <UFormField :label="$t('admin.ordersSection.trackingNumber')">
            <UInput
              v-model="shipmentDraft(shippingOrder).trackingNumber"
              :placeholder="$t('admin.ordersSection.trackingNumberPlaceholder')"
              class="w-full"
              @keyup.enter="shippingOrder && recordShipment(shippingOrder)"
            />
          </UFormField>

          <!-- The hint is a footnote, not an instruction: it explains what
               happens if you skip the field. As a line of body text it pushed
               the input down and read as heavily as the labels above it.
               `labelWrapper` is already `justify-between`, so the hint slot
               sits at the end of the label row on its own. -->
          <UFormField :label="$t('admin.ordersSection.trackingUrl')">
            <template #hint>
              <UTooltip
                :text="$t('admin.ordersSection.trackingUrlHint')"
                :delay-duration="150"
              >
                <UButton
                  data-testid="tracking-url-hint"
                  variant="link"
                  color="neutral"
                  size="xs"
                  square
                  class="p-0"
                  icon="i-lucide-info"
                  :aria-label="$t('admin.ordersSection.trackingUrlHint')"
                />
              </UTooltip>
            </template>
            <UInput
              v-model="shipmentDraft(shippingOrder).trackingUrl"
              type="url"
              placeholder="https://"
              class="w-full"
            />
          </UFormField>

          <UCheckbox
            v-model="shipmentDraft(shippingOrder).notify"
            :label="shippingOrder.shipped_at
              ? $t('admin.ordersSection.notifyBuyerAgain')
              : $t('admin.ordersSection.notifyBuyer')"
          />
        </div>
      </template>

      <template #footer>
        <div class="flex items-center justify-end gap-2 w-full">
          <UButton
            variant="ghost"
            color="neutral"
            :label="$t('admin.ordersSection.cancel')"
            @click="shippingOrder = null"
          />
          <UButton
            icon="i-lucide-truck"
            :label="shippingOrder?.shipped_at
              ? $t('admin.ordersSection.updateShipment')
              : $t('admin.ordersSection.recordShipment')"
            :loading="busy === shippingOrder?.id"
            @click="shippingOrder && recordShipment(shippingOrder)"
          />
        </div>
      </template>
    </UModal>
  </div>
</template>
