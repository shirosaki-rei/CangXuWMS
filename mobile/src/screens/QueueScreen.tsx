/** 待同步队列（接口 58 的客户端侧）。 */
import { useCallback, useEffect, useState } from 'react'
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import { flush, listOps, retryFailed, type PendingOp } from '../db/queue'
import { useSession } from '../stores/session'

export default function QueueScreen() {
  const { session } = useSession()
  const [ops, setOps] = useState<PendingOp[]>([])
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const reload = useCallback(async () => setOps(await listOps()), [])

  useEffect(() => { void reload() }, [reload])

  async function onFlush() {
    if (!session) return
    setBusy(true)
    try {
      const r = await flush(session.apiBase, session.token)
      setMsg(
        r.error
          ? `同步中断：${r.error}`
          : `共 ${r.total} 条 → 成功 ${r.ok}，重复 ${r.duplicate}，失败 ${r.failed}`,
      )
      await reload()
    } finally {
      setBusy(false)
    }
  }

  async function onRetry() {
    await retryFailed()
    setMsg('失败项已重置为待同步')
    await reload()
  }

  return (
    <ScrollView contentContainerStyle={s.wrap}>
      <Text style={s.title}>待同步队列</Text>
      <Text style={s.hint}>
        断网时的扫码都会先落到本地 SQLite，网络恢复后按扫码时间顺序补传。
        单条失败不影响后续（BR-012）。
      </Text>

      <View style={s.btnRow}>
        <Pressable style={[s.btn, busy && { opacity: 0.6 }]} onPress={onFlush} disabled={busy}>
          <Text style={s.btnText}>{busy ? '同步中…' : '立即同步'}</Text>
        </Pressable>
        <Pressable style={[s.btn, s.btnGhost]} onPress={onRetry}>
          <Text style={[s.btnText, { color: '#0d5bb5' }]}>重试失败项</Text>
        </Pressable>
      </View>
      {!!msg && <Text style={s.msg}>{msg}</Text>}

      <Text style={s.section}>共 {ops.length} 条</Text>
      {ops.map((o) => (
        <View key={o.client_op_id} style={[s.card, o.status === 'FAILED' && s.cardFail]}>
          <View style={s.cardHead}>
            <Text style={s.opType}>{o.op_type}</Text>
            <Text style={[s.badge, o.status === 'FAILED' ? s.badgeFail : s.badgeOk]}>
              {o.status === 'FAILED' ? `失败 ×${o.retries}` : '待同步'}
            </Text>
          </View>
          <Text style={s.path}>{o.path}</Text>
          <Text style={s.meta}>{o.created_at}</Text>
          {!!o.error && <Text style={s.err}>{o.error}</Text>}
        </View>
      ))}
      {!ops.length && <Text style={s.hint}>队列是空的</Text>}
    </ScrollView>
  )
}

const s = StyleSheet.create({
  wrap: { padding: 16, paddingTop: 24, backgroundColor: '#f4f7fb', flexGrow: 1 },
  title: { fontSize: 20, fontWeight: '700', color: '#12263a' },
  hint: { color: '#8494a3', fontSize: 12, marginTop: 6, lineHeight: 18 },
  btnRow: { flexDirection: 'row', gap: 10, marginTop: 14 },
  btn: {
    flex: 1, backgroundColor: '#1891ff', borderRadius: 6, paddingVertical: 12,
    alignItems: 'center',
  },
  btnGhost: { backgroundColor: '#fff', borderWidth: 1, borderColor: '#1891ff' },
  btnText: { color: '#fff', fontWeight: '600' },
  msg: { marginTop: 10, color: '#0d5bb5', fontSize: 13 },
  section: { marginTop: 18, marginBottom: 8, fontWeight: '600', color: '#12263a' },
  card: {
    backgroundColor: '#fff', borderRadius: 8, padding: 12, marginBottom: 8,
    borderWidth: 1, borderColor: '#e9eef4',
  },
  cardFail: { borderColor: '#f3c7cf', backgroundColor: '#fff8f9' },
  cardHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  opType: { fontWeight: '600', color: '#12263a' },
  badge: { fontSize: 11, paddingHorizontal: 8, paddingVertical: 2, borderRadius: 10 },
  badgeOk: { backgroundColor: '#e8f3ff', color: '#0d5bb5' },
  badgeFail: { backgroundColor: '#fdecef', color: '#d03050' },
  path: { color: '#5b6b7a', fontSize: 12, marginTop: 4, fontFamily: 'monospace' },
  meta: { color: '#a6b0ba', fontSize: 11, marginTop: 2 },
  err: { color: '#d03050', fontSize: 12, marginTop: 4 },
})
