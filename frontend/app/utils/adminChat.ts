/** One row of `GET {ADMIN}/chats`, shared by the list and its container. */
export interface ChatSummary {
  user_id: string
  display_name: string
  avatar_url: string | null
  message_count: number
  last_message: string
  last_role: string
  unread: boolean
  ai_enabled?: boolean
  admin_intervening?: boolean
  last_activity?: string | null
  admin_last_read_at?: string | null
  // SPEC-063 — soft archive state, and the identity the customer panel shows.
  archived?: boolean
  archived_at?: string | null
  email?: string | null
  created_at?: string | null
  is_banned?: boolean
}
