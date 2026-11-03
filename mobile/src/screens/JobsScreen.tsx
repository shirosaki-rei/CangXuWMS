/** 作业列表（A06/A07 合并）：待入库 + 待出库，点进去接着扫码。 */
import { useCallback, useEffect, useState } from 'react'
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'
import { request } from '../api/client'
import { useSession } from '../stores/session'

interface Order {
  id: number
  no: string
  type_label: string
  source_no: string | null
  status_label: string
  plan_qty: number
  actual_qty: number
  created_at: string
}

export default function JobsScreen({ navigation }: any) {
  const { session } = useSession()
  const [inbound, setInbound] = useState<Order[]>([])
  const [outbound, setOutbound] = useState<Order[]>([])
  const [refreshing, setRefreshing] = useState(false)
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    if (!session) return
    setRefreshing(true)
    try {
      const [i, o] = await Promise.all([
        request<{ items: Order[] }>({
          base: session.apiBase, token: session.token,
          path: '/inbound-orders?status=PENDING&page_size=50',
        }),
        request<{ items: Order[] }>({
          base: session.apiBase, token: session.token,
          path: '/outbound-orders?status=PENDING&page_size=50',
        }),
      ])
      setInbound(i.data.items)
      setOutbound(o.data.items)
      setErr('')
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setRefreshing(false)
    }
  }, [session])

  useEffect(() => { void load() }, [load])

  return (
    <ScrollView
      contentContainerStyle={s.wrap}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} />}
    >
      <Text style={s.title}>作业</Text>
      {!!err && <Text style={s.err}>{err}</Text>}

      <Text style={s.section}>待入库（{inbound.length}）</Text>
      {inbound.map((o) => (
        <Pressable
          key={o.id}
          style={s.card}
          onPress={() => navigation.navigate('扫码', { orderId: o.id })}
        >
          <View style={s.cardHead}>
            <Text style={s.no}>{o.no}</Text>
            <Text style={s.tag}>{o.type_label}</Text>
          </View>
          <Text style={s.meta}>
            来源 {o.source_no ?? '—'} · {o.actual_qty}/{o.plan_qty}
          </Text>
        </Pressable>
      ))}
      {!inbound.length && <Text style={s.hint}>没有待入库单据</Text>}

      <Text style={s.section}>待出库（{outbound.length}）</Text>
      {outbound.map((o) => (
        <Pressable
          key={o.id}
          style={s.card}
          onPress={() => navigation.navigate('库内', { outboundId: o.id })}
        >
          <View style={s.cardHead}>
            <Text style={s.no}>{o.no}</Text>
            <Text style={s.tag}>{o.type_label}</Text>
          </View>
          <Text style={s.meta}>
            来源 {o.source_no ?? '—'} · {o.actual_qty}/{o.plan_qty}
          </Text>
        </Pressable>
      ))}
      {!outbound.length && <Text style={s.hint}>没有待出库单据</Text>}

      <Text style={s.note}>
        出库拣货页在 B04 只做到「列表 + 跳转」，完整拣货交互随 X03 拣货路径一起做。
      </Text>
    </ScrollView>
  )
}

const s = StyleSheet.create({
  wrap: { padding: 16, paddingTop: 24, backgroundColor: '#f4f7fb', flexGrow: 1 },
  title: { fontSize: 20, fontWeight: '700', color: '#12263a' },
  err: { color: '#d03050', marginTop: 8, fontSize: 13 },
  section: { marginTop: 18, marginBottom: 8, fontWeight: '600', color: '#12263a' },
  card: {
    backgroundColor: '#fff', borderRadius: 8, padding: 12, marginBottom: 8,
    borderWidth: 1, borderColor: '#e9eef4',
  },
  cardHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  no: { fontFamily: 'monospace', fontSize: 14, color: '#12263a', fontWeight: '600' },
  tag: { fontSize: 11, color: '#0d5bb5', backgroundColor: '#e8f3ff', paddingHorizontal: 8, paddingVertical: 2, borderRadius: 10 },
  meta: { color: '#8494a3', fontSize: 12, marginTop: 4 },
  hint: { color: '#a6b0ba', fontSize: 12, marginBottom: 6 },
  note: { color: '#8494a3', fontSize: 12, lineHeight: 18, marginTop: 20 },
})
