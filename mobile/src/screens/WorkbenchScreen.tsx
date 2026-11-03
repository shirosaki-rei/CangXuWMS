/** 工作台（A01 骨架）。只列已接通的入口，没做的一律不放，避免点进去空转。 */
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import { useEffect, useState } from 'react'
import { countOps } from '../db/queue'
import { useSession } from '../stores/session'

const ENTRIES = [
  { key: 'scan', title: '扫码收货', desc: 'A02/A03 · 摄像头或激光头', tab: '扫码' },
  { key: 'queue', title: '待同步', desc: '离线队列与补传', tab: '待同步' },
  { key: 'diag', title: 'PDA 打样', desc: '环境自检与扫码验证', tab: '诊断' },
]

export default function WorkbenchScreen({ navigation }: any) {
  const { session, signOut } = useSession()
  const [counts, setCounts] = useState({ pending: 0, failed: 0 })

  useEffect(() => {
    const t = setInterval(() => { void countOps().then(setCounts) }, 1500)
    void countOps().then(setCounts)
    return () => clearInterval(t)
  }, [])

  return (
    <ScrollView contentContainerStyle={s.wrap}>
      <Text style={s.title}>工作台</Text>
      <Text style={s.sub}>
        {session?.name} · {session?.role} · 可见仓库 {session?.warehouses.length ?? 0} 个
      </Text>

      {(counts.pending > 0 || counts.failed > 0) && (
        <View style={s.alert}>
          <Text style={s.alertText}>
            待同步 {counts.pending} 条{counts.failed ? `，失败 ${counts.failed} 条` : ''}
          </Text>
        </View>
      )}

      <View style={s.grid}>
        {ENTRIES.map((e) => (
          <Pressable key={e.key} style={s.card} onPress={() => navigation.navigate(e.tab)}>
            <Text style={s.cardTitle}>{e.title}</Text>
            <Text style={s.cardDesc}>{e.desc}</Text>
          </Pressable>
        ))}
      </View>

      <Text style={s.note}>
        本版本只交付「骨架 + 扫码打样」：登录、扫码、离线队列、补传、环境自检。
        入库/出库/盘点等作业页在 B04 按批次补齐。
      </Text>

      <Pressable style={s.signOut} onPress={() => void signOut()}>
        <Text style={s.signOutText}>退出登录</Text>
      </Pressable>
    </ScrollView>
  )
}

const s = StyleSheet.create({
  wrap: { padding: 16, paddingTop: 24, backgroundColor: '#f4f7fb', flexGrow: 1 },
  title: { fontSize: 22, fontWeight: '700', color: '#12263a' },
  sub: { color: '#7b8a99', marginTop: 4, marginBottom: 14 },
  alert: {
    backgroundColor: '#fff7e6', borderWidth: 1, borderColor: '#ffd591', borderRadius: 6,
    padding: 10, marginBottom: 12,
  },
  alertText: { color: '#ad6800', fontSize: 13 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  card: {
    width: '47%', backgroundColor: '#fff', borderRadius: 10, padding: 16,
    borderWidth: 1, borderColor: '#e9eef4',
  },
  cardTitle: { fontSize: 16, fontWeight: '600', color: '#12263a' },
  cardDesc: { color: '#8494a3', fontSize: 12, marginTop: 6, lineHeight: 17 },
  note: { color: '#8494a3', fontSize: 12, lineHeight: 19, marginTop: 20 },
  signOut: { marginTop: 28, alignItems: 'center', paddingVertical: 12 },
  signOutText: { color: '#d03050', fontSize: 14 },
})
