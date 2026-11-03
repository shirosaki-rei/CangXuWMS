/**
 * 库内作业（A09）：物料盘点 + 物料移位。
 *
 * 移位是 PRD 的「三扫」流程：扫源库位 → 扫物料 → 扫目标库位 → 确认。
 * 三个输入框都可以用下方扫码区填，也可以手输，现场哪种顺手用哪种。
 */
import { useCallback, useEffect, useState } from 'react'
import {
  ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native'
import { CameraView, useCameraPermissions } from 'expo-camera'
import { request } from '../api/client'
import { useSession } from '../stores/session'

type Tab = 'stocktake' | 'move'

interface Stocktake {
  id: number
  no: string
  mode: string
  mode_label: string
  status: string
  status_label: string
  total: number
  done: number
  undone: number
}
interface Item {
  id: number
  material_id: number
  material_code: string
  material_name: string
  location_id: number
  location_code: string
  real_qty: number | null
  counted: boolean
}
interface MaterialRow { id: number; code: string; name: string; unit: string }
interface LocationRow { id: number; code: string; warehouse_name: string; status: string }

export default function WarehouseScreen() {
  const { session } = useSession()
  const [tab, setTab] = useState<Tab>('stocktake')
  const [perm] = useCameraPermissions()
  const [scanTarget, setScanTarget] = useState<null | 'src' | 'mat' | 'dst' | 'item'>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  // 盘点状态
  const [sheet, setSheet] = useState<Stocktake | null>(null)
  const [items, setItems] = useState<Item[]>([])
  const [qty, setQty] = useState('')

  // 移位状态
  const [srcCode, setSrcCode] = useState('')
  const [matCode, setMatCode] = useState('')
  const [dstCode, setDstCode] = useState('')
  const [moveQty, setMoveQty] = useState('1')
  const [materials, setMaterials] = useState<MaterialRow[]>([])
  const [locations, setLocations] = useState<LocationRow[]>([])

  const api = useCallback(
    <T,>(path: string, method: 'GET' | 'POST' = 'GET', body?: unknown) =>
      request<T>({ base: session!.apiBase, token: session!.token, method, path, body }),
    [session],
  )

  async function loadStocktakes() {
    if (!session) return
    setBusy(true)
    try {
      const r = await api<{ items: Stocktake[] }>('/stocktakes?page_size=50')
      setSheet(r.data.items.find((x) => x.status !== 'DONE') ?? null)
      if (sheet) await openSheet(sheet.id)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function openSheet(id: number) {
    const [d, it] = await Promise.all([
      api<Stocktake>(`/stocktakes/${id}`),
      api<Item[]>(`/stocktakes/${id}/items`),
    ])
    setSheet(d.data)
    setItems(it.data)
    setErr('')
  }

  async function loadRefs() {
    if (!session) return
    try {
      const [m, l] = await Promise.all([
        api<{ items: MaterialRow[] }>('/inventory/materials?page_size=100'),
        api<{ items: LocationRow[] }>('/locations?page_size=100'),
      ])
      setMaterials(m.data.items)
      setLocations(l.data.items)
    } catch (e) {
      setErr((e as Error).message)
    }
  }

  useEffect(() => {
    if (tab === 'stocktake') void loadStocktakes()
    else void loadRefs()
  }, [tab])

  // ---------------------------------------------------------------- 扫码回填
  function onScan({ data }: { data: string }) {
    const v = data.trim()
    if (scanTarget === 'src') setSrcCode(v)
    else if (scanTarget === 'mat') setMatCode(v)
    else if (scanTarget === 'dst') setDstCode(v)
    else if (scanTarget === 'item') {
      const hit = items.find((i) => i.location_code === v || i.material_code === v)
      if (hit) {
        setQty(String(hit.real_qty ?? ''))
        setMsg(`已定位：${hit.material_name} @ ${hit.location_code}`)
      } else setMsg(`没有匹配的盘点行：${v}`)
    }
    setScanTarget(null)
  }

  // ---------------------------------------------------------------- 盘点
  async function submitCount(item: Item) {
    const n = Number(qty)
    if (Number.isNaN(n) || n < 0) {
      setErr('实盘数必须是非负整数')
      return
    }
    setBusy(true)
    try {
      await api(`/stocktakes/${sheet!.id}/count`, 'POST', {
        location_id: item.location_id, material_id: item.material_id, real_qty: n,
      })
      setQty('')
      await openSheet(sheet!.id)
      setMsg('已记录实盘数')
      setErr('')
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  // ---------------------------------------------------------------- 移位
  async function doMove() {
    const src = locations.find((l) => l.code === srcCode.trim())
    const dst = locations.find((l) => l.code === dstCode.trim())
    const mat = materials.find((m) => m.code === matCode.trim())
    if (!src || !dst) { setErr('源库位或目标库位编码不存在'); return }
    if (!mat) { setErr('物料编码不存在'); return }
    const n = Number(moveQty)
    if (!n || n <= 0) { setErr('数量必须大于 0'); return }

    setBusy(true)
    try {
      const r = await api<{ no: string; source_remain: number }>('/move-orders', 'POST', {
        material_id: mat.id, from_location_id: src.id, to_location_id: dst.id, qty: n,
      })
      setMsg(`移位单 ${r.data.no} 完成，源库位剩余 ${r.data.source_remain}`)
      setErr('')
      setMatCode(''); setMoveQty('1')
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const scandable = perm?.granted

  return (
    <ScrollView contentContainerStyle={s.wrap} keyboardShouldPersistTaps="handled">
      <Text style={s.title}>库内作业</Text>

      <View style={s.seg}>
        {(['stocktake', 'move'] as Tab[]).map((t) => (
          <Pressable key={t} style={[s.segItem, tab === t && s.segOn]} onPress={() => setTab(t)}>
            <Text style={[s.segText, tab === t && s.segTextOn]}>
              {t === 'stocktake' ? '物料盘点' : '物料移位'}
            </Text>
          </Pressable>
        ))}
      </View>

      {!!err && <Text style={s.err}>{err}</Text>}
      {!!msg && <Text style={s.msg}>{msg}</Text>}

      {scanTarget && (
        <View style={s.camBox}>
          {scandable ? (
            <CameraView
              style={StyleSheet.absoluteFill}
              barcodeScannerSettings={{ barcodeTypes: ['code128', 'code39', 'ean13', 'qr'] }}
              onBarcodeScanned={onScan}
            />
          ) : (
            <Text style={s.hint}>未授予摄像头权限，请手输</Text>
          )}
          <Pressable style={s.camClose} onPress={() => setScanTarget(null)}>
            <Text style={s.camCloseText}>关闭</Text>
          </Pressable>
        </View>
      )}

      {tab === 'stocktake' ? (
        <>
          {!sheet && <Text style={s.hint}>没有进行中的盘点单，请先在 PC 端创建</Text>}
          {sheet && (
            <>
              <View style={s.card}>
                <View style={s.cardHead}>
                  <Text style={s.no}>{sheet.no}</Text>
                  <Text style={s.tag}>{sheet.mode_label}</Text>
                </View>
                <Text style={s.meta}>
                  {sheet.status_label} · 已盘 {sheet.done}/{sheet.total}
                  {sheet.undone ? ` · 未盘 ${sheet.undone}` : ''}
                </Text>
              </View>

              {items.map((it) => (
                <Pressable
                  key={it.id}
                  style={[s.item, it.counted && s.itemDone]}
                  onPress={() => { setQty(String(it.real_qty ?? '')); setMsg(`选中 ${it.material_name}`) }}
                >
                  <View style={{ flex: 1 }}>
                    <Text style={s.itemName}>{it.material_name}</Text>
                    <Text style={s.meta}>{it.material_code} · {it.location_code}</Text>
                  </View>
                  <Text style={[s.qty, it.counted && s.qtyDone]}>
                    {it.counted ? it.real_qty : '未盘'}
                  </Text>
                </Pressable>
              ))}

              <View style={s.row}>
                <TextInput
                  style={[s.input, { flex: 1 }]}
                  value={qty}
                  onChangeText={setQty}
                  keyboardType="number-pad"
                  placeholder="实盘数（先点选上面的行）"
                />
                <Pressable style={s.btn} onPress={() => { setScanTarget('item'); }}>
                  <Text style={s.btnText}>扫码定位</Text>
                </Pressable>
              </View>
              <Pressable
                style={[s.btn, s.btnPrimary]}
                onPress={() => {
                  const last = items.find((i) => !i.counted) ?? items[0]
                  if (last) void submitCount(last)
                }}
              >
                <Text style={s.btnText}>确认实盘数</Text>
              </Pressable>
              <Text style={s.hint}>
                盲盘模式下账面数不显示，提交后由主管在 PC 端确认揭晓。
              </Text>
            </>
          )}
        </>
      ) : (
        <>
          <Text style={s.label}>1. 扫源库位</Text>
          <View style={s.row}>
            <TextInput style={[s.input, { flex: 1 }]} value={srcCode} onChangeText={setSrcCode}
                       autoCapitalize="characters" placeholder="如 A1-01-01" />
            <Pressable style={s.btn} onPress={() => setScanTarget('src')}>
              <Text style={s.btnText}>扫</Text>
            </Pressable>
          </View>

          <Text style={s.label}>2. 扫物料</Text>
          <View style={s.row}>
            <TextInput style={[s.input, { flex: 1 }]} value={matCode} onChangeText={setMatCode}
                       autoCapitalize="characters" placeholder="如 BAT-LIPO-4500-003" />
            <Pressable style={s.btn} onPress={() => setScanTarget('mat')}>
              <Text style={s.btnText}>扫</Text>
            </Pressable>
          </View>

          <Text style={s.label}>3. 扫目标库位</Text>
          <View style={s.row}>
            <TextInput style={[s.input, { flex: 1 }]} value={dstCode} onChangeText={setDstCode}
                       autoCapitalize="characters" placeholder="如 A1-02-01" />
            <Pressable style={s.btn} onPress={() => setScanTarget('dst')}>
              <Text style={s.btnText}>扫</Text>
            </Pressable>
          </View>

          <Text style={s.label}>数量</Text>
          <TextInput style={s.input} value={moveQty} onChangeText={setMoveQty}
                     keyboardType="number-pad" />

          <Pressable style={[s.btn, s.btnPrimary]} onPress={doMove} disabled={busy}>
            <Text style={s.btnText}>{busy ? '提交中…' : '确认移位'}</Text>
          </Pressable>
          {busy && <ActivityIndicator style={{ marginTop: 10 }} />}
        </>
      )}
    </ScrollView>
  )
}

const s = StyleSheet.create({
  wrap: { padding: 16, paddingTop: 24, backgroundColor: '#f4f7fb', flexGrow: 1 },
  title: { fontSize: 20, fontWeight: '700', color: '#12263a' },
  seg: { flexDirection: 'row', backgroundColor: '#e6edf5', borderRadius: 8, padding: 3, marginVertical: 14 },
  segItem: { flex: 1, alignItems: 'center', paddingVertical: 8, borderRadius: 6 },
  segOn: { backgroundColor: '#fff' },
  segText: { color: '#5b6b7a', fontSize: 14 },
  segTextOn: { color: '#0d5bb5', fontWeight: '600' },
  err: { color: '#d03050', marginTop: 8, fontSize: 13 },
  msg: { color: '#0d5bb5', marginTop: 8, fontSize: 13 },
  camBox: { height: 200, borderRadius: 10, overflow: 'hidden', backgroundColor: '#000', marginBottom: 10 },
  camClose: { position: 'absolute', right: 8, top: 8, backgroundColor: 'rgba(0,0,0,0.6)', paddingHorizontal: 10, paddingVertical: 4, borderRadius: 12 },
  camCloseText: { color: '#fff', fontSize: 12 },
  card: { backgroundColor: '#fff', borderRadius: 8, padding: 12, borderWidth: 1, borderColor: '#e9eef4' },
  cardHead: { flexDirection: 'row', justifyContent: 'space-between' },
  no: { fontFamily: 'monospace', fontWeight: '600', color: '#12263a' },
  tag: { fontSize: 11, color: '#ad6800', backgroundColor: '#fff7e6', paddingHorizontal: 8, paddingVertical: 2, borderRadius: 10 },
  meta: { color: '#8494a3', fontSize: 12, marginTop: 4 },
  item: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#fff', borderRadius: 8, padding: 12, marginTop: 8, borderWidth: 1, borderColor: '#e9eef4' },
  itemDone: { borderColor: '#b7e3c6', backgroundColor: '#f6fdf8' },
  itemName: { color: '#12263a', fontWeight: '600' },
  qty: { color: '#a6b0ba', fontWeight: '600' },
  qtyDone: { color: '#18a058' },
  label: { fontSize: 12, color: '#6b7b8a', marginTop: 12, marginBottom: 4 },
  row: { flexDirection: 'row', gap: 8, alignItems: 'center' },
  input: { backgroundColor: '#fff', borderWidth: 1, borderColor: '#dde2e8', borderRadius: 6, paddingHorizontal: 10, paddingVertical: 9, fontSize: 15 },
  btn: { backgroundColor: '#e8f3ff', borderRadius: 6, paddingHorizontal: 14, paddingVertical: 10, alignItems: 'center' },
  btnPrimary: { backgroundColor: '#1891ff', marginTop: 14 },
  btnText: { color: '#0d5bb5', fontWeight: '600' },
  hint: { color: '#8494a3', fontSize: 12, marginTop: 10, lineHeight: 18 },
})
