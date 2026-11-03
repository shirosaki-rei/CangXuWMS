/**
 * 扫码作业（A02/A03 的骨架）。
 *
 * 只做一件事：把「扫到的码」变成一条可补传的 INBOUND_SCAN 操作。
 * 入队之后再尽力同步一次——在线就当场成功，离线就留在本地等网络恢复，
 * 这正是 T-01-7 要验证的主路径。
 *
 * 两种输入方式都要测：
 *   摄像头    —— Expo 自带，兼容性未知，是打样的主要风险
 *   键盘楔入  —— 工业 PDA 的激光头通常就是「打字 + 回车」，不需要任何库
 */
import { useCallback, useRef, useState } from 'react'
import {
  ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native'
import { CameraView, useCameraPermissions } from 'expo-camera'
import { newOpId } from '../config'
import { enqueue, flush } from '../db/queue'
import { useSession } from '../stores/session'

type Mode = 'camera' | 'wedge'

interface ScanLog {
  id: string
  value: string
  symbology: string
  at: string
  ms: number
}

export default function ScanScreen({ route }: any) {
  const { session } = useSession()
  const [mode, setMode] = useState<Mode>('camera')
  const [orderId, setOrderId] = useState(String(route?.params?.orderId ?? ''))
  const [locationId, setLocationId] = useState(String(route?.params?.locationId ?? ''))
  const [log, setLog] = useState<ScanLog[]>([])
  const [busy, setBusy] = useState(false)
  const [hint, setHint] = useState('')
  const [permission, requestPermission] = useCameraPermissions()

  // 防止摄像头一秒扫几十次
  const lastRef = useRef<{ value: string; at: number }>({ value: '', at: 0 })
  // 键盘楔入的按键时序，用来自检「这是扫码枪还是人手打的」
  const keyTimes = useRef<number[]>([])

  const handleCode = useCallback(
    async (value: string, symbology: string) => {
      const now = Date.now()
      if (lastRef.current.value === value && now - lastRef.current.at < 1500) return
      lastRef.current = { value, at: now }

      const oid = Number(orderId)
      const lid = Number(locationId)
      if (!oid || !lid) {
        setHint('先填入库单 id 和库位 id')
        return
      }

      const opId = newOpId()
      await enqueue({
        clientOpId: opId,
        opType: 'INBOUND_SCAN',
        path: `/api/v1/inbound-orders/${oid}/scan`,
        body: { order_id: oid, box_code: value, location_id: lid, qty: 1 },
      })
      setLog((l) => [
        { id: opId, value, symbology, at: new Date().toLocaleTimeString(), ms: now },
        ...l,
      ].slice(0, 30))

      // 在线就顺手同步；网络错误静默留在队列里
      if (session) {
        setBusy(true)
        try {
          const r = await flush(session.apiBase, session.token)
          setHint(
            r.error
              ? `已入队，暂未同步：${r.error}`
              : `已同步 ${r.ok} 条${r.duplicate ? `，重复 ${r.duplicate}` : ''}${r.failed ? `，失败 ${r.failed}` : ''}`,
          )
        } finally {
          setBusy(false)
        }
      }
    },
    [orderId, locationId, session],
  )

  function onBarcode({ type, data }: { type: string; data: string }) {
    void handleCode(data, type)
  }

  function onWedgeChange(text: string) {
    const now = Date.now()
    keyTimes.current.push(now)
    if (keyTimes.current.length > 30) keyTimes.current.shift()

    if (text.endsWith('\n')) {
      const value = text.trim()
      if (value) void handleCode(value, 'KEYBOARD_WEDGE')
      setWedgeText('')
    } else {
      setWedgeText(text)
    }
  }

  const [wedgeText, setWedgeText] = useState('')

  function avgKeyMs(): number {
    const t = keyTimes.current
    if (t.length < 3) return 0
    let sum = 0
    for (let i = 1; i < t.length; i++) sum += t[i] - t[i - 1]
    return Math.round(sum / (t.length - 1))
  }

  return (
    <ScrollView contentContainerStyle={s.wrap} keyboardShouldPersistTaps="handled">
      <Text style={s.title}>扫码作业</Text>

      <View style={s.row}>
        <View style={{ flex: 1 }}>
          <Text style={s.label}>入库单 id</Text>
          <TextInput style={s.input} value={orderId} onChangeText={setOrderId} keyboardType="number-pad" />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={s.label}>库位 id</Text>
          <TextInput style={s.input} value={locationId} onChangeText={setLocationId} keyboardType="number-pad" />
        </View>
      </View>

      <View style={s.seg}>
        {(['camera', 'wedge'] as Mode[]).map((m) => (
          <Pressable
            key={m}
            style={[s.segItem, mode === m && s.segOn]}
            onPress={() => setMode(m)}
          >
            <Text style={[s.segText, mode === m && s.segTextOn]}>
              {m === 'camera' ? '摄像头' : '键盘楔入'}
            </Text>
          </Pressable>
        ))}
      </View>

      {mode === 'camera' ? (
        permission?.granted ? (
          <View style={s.camBox}>
            <CameraView
              style={StyleSheet.absoluteFill}
              facing="back"
              barcodeScannerSettings={{ barcodeTypes: ['code128', 'code39', 'ean13', 'qr'] }}
              onBarcodeScanned={onBarcode}
            />
          </View>
        ) : (
          <Pressable style={s.permBtn} onPress={requestPermission}>
            <Text style={s.permText}>
              {permission ? '授予摄像头权限后开始扫码' : '正在读取权限…'}
            </Text>
          </Pressable>
        )
      ) : (
        <View>
          <TextInput
            style={[s.input, s.wedge]}
            value={wedgeText}
            onChangeText={onWedgeChange}
            autoFocus
            autoCorrect={false}
            autoCapitalize="characters"
            placeholder="把光标放这里，用激光头扫一次"
          />
          <Text style={s.hint}>
            平均按键间隔 {avgKeyMs()} ms
            {avgKeyMs() > 0 && avgKeyMs() < 50 ? '（像扫码枪）' : avgKeyMs() >= 50 ? '（像人手输入）' : ''}
          </Text>
        </View>
      )}

      {busy && <ActivityIndicator style={{ marginTop: 10 }} />}
      {!!hint && <Text style={s.hint}>{hint}</Text>}

      <Text style={s.section}>本次扫码（{log.length}）</Text>
      {log.map((l) => (
        <View key={l.id} style={s.logRow}>
          <Text style={s.logCode}>{l.value}</Text>
          <Text style={s.logMeta}>{l.symbology} · {l.at}</Text>
        </View>
      ))}
      {!log.length && <Text style={s.hint}>还没有扫码记录</Text>}
    </ScrollView>
  )
}

const s = StyleSheet.create({
  wrap: { padding: 16, paddingTop: 24, backgroundColor: '#f4f7fb', flexGrow: 1 },
  title: { fontSize: 20, fontWeight: '700', color: '#12263a', marginBottom: 12 },
  row: { flexDirection: 'row', gap: 10 },
  label: { fontSize: 12, color: '#6b7b8a', marginBottom: 4, marginTop: 8 },
  input: {
    backgroundColor: '#fff', borderWidth: 1, borderColor: '#dde2e8', borderRadius: 6,
    paddingHorizontal: 10, paddingVertical: 9, fontSize: 15,
  },
  seg: {
    flexDirection: 'row', backgroundColor: '#e6edf5', borderRadius: 8, padding: 3,
    marginVertical: 14,
  },
  segItem: { flex: 1, alignItems: 'center', paddingVertical: 8, borderRadius: 6 },
  segOn: { backgroundColor: '#fff' },
  segText: { color: '#5b6b7a', fontSize: 14 },
  segTextOn: { color: '#0d5bb5', fontWeight: '600' },
  camBox: {
    height: 260, borderRadius: 10, overflow: 'hidden', backgroundColor: '#000',
  },
  permBtn: {
    height: 120, borderRadius: 10, backgroundColor: '#fff', borderWidth: 1,
    borderColor: '#dde2e8', alignItems: 'center', justifyContent: 'center',
  },
  permText: { color: '#0d5bb5', fontSize: 15 },
  wedge: { height: 64, fontSize: 18 },
  hint: { color: '#8494a3', fontSize: 12, marginTop: 8 },
  section: { marginTop: 20, marginBottom: 8, fontWeight: '600', color: '#12263a' },
  logRow: {
    backgroundColor: '#fff', borderRadius: 6, padding: 10, marginBottom: 6,
    borderWidth: 1, borderColor: '#e9eef4',
  },
  logCode: { fontFamily: 'monospace', fontSize: 14, color: '#12263a' },
  logMeta: { color: '#8494a3', fontSize: 11, marginTop: 2 },
})
